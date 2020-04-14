#!/usr/bin/env python3
"""
Thingiverse bulk downloader
"""

import re
import sys
import os
import argparse
import unicodedata
import requests
import logging
import multiprocessing
import enum
import datetime
from shutil import copyfile
from bs4 import BeautifulSoup
from dataclasses import dataclass
import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options

URL_BASE = "https://www.thingiverse.com"
URL_COLLECTION = URL_BASE + "/ajax/thingcollection/list_collected_things"
USER_COLLECTION = URL_BASE + "/ajax/user/designs"

ID_REGEX = re.compile(r'"id":(\d*),')
TOTAL_REGEX = re.compile(r'"total":(\d*),')
LAST_PAGE_REGEX = re.compile(r'"last_page":(\d*),')
# This appears to be fixed at 12, but if it changes would screw the rest up.
PER_PAGE_REGEX = re.compile(r'"per_page":(\d*),')
NO_WHITESPACE_REGEX = re.compile(r'[-\s]+')

DOWNLOADER_COUNT = 1
RETRY_COUNT = 3

VERSION = "0.8.3"


#BROWSER = webdriver.PhantomJS('./phantomjs')
options = Options()
options.add_argument("--headless")
BROWSER = webdriver.Firefox(options=options)

BROWSER.set_window_size(1980, 1080)


@dataclass
class FileLink:
    name: str
    last_update: str
    link: datetime.datetime
    

class State(enum.Enum):
    OK = enum.auto()
    FAILED = enum.auto()
    ALREADY_DOWNLOADED = enum.auto()


def strip_ws(value):
    """ Remove whitespace from a string """
    return str(NO_WHITESPACE_REGEX.sub('-', value))


def strip_invalid_chars(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters.
    """
    return unicodedata.normalize('NFKD', value).encode(
        'ascii', 'ignore').decode()


def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = strip_invalid_chars(value)
    value = str(re.sub(r'[^\w\s-]', '', value).strip())
    value = strip_ws(value)
    return value

class PageChecker(object):
    def __init__(self):
        self.log = []
        self.title = None
        self.file_count = None
        self.files = None
        self.images = None
        self.license = None


    def __call__(self, _):
        try:
            self.log.append("call")
            if self.title is None:
                # first find the name
                name = EC._find_element(BROWSER, (By.CSS_SELECTOR, "[class^=ThingPage__modelName]"))
                if name is None: 
                    return False
                self.title = name.text

            if self.file_count is None:
                # OK. Do we know how many files we have to download?
                metrics = EC._find_elements(BROWSER, (By.CSS_SELECTOR, "[class^=MetricButton]"))
                self.log.append("got some metrics: {}".format(len(metrics)))
                cur_count = int([x.text.split("\n")[0] for x in metrics if x.text.endswith("\nThing Files")][0])
                self.log.append(cur_count)
                if cur_count == 0:
                    return False
                self.file_count = cur_count
                
            self.log.append("looking for {} files".format(self.file_count))
            fileRows = EC._find_elements(BROWSER, (By.CSS_SELECTOR, "[class^=ThingFile__fileRow]"))
            self.log.append("found {} files".format(len(fileRows)))
            if len(fileRows) < self.file_count:
                return False

            self.log.append("Looking for images")
            # By this point _should_ have loaded all the images
            self.images = EC._find_elements(BROWSER, (By.CSS_SELECTOR, "[class^=thumb]"))
            self.license = EC._find_element(BROWSER, (By.CSS_SELECTOR, "[class^=License__licenseText]")).text
            self.log.append("found {} images".format(len(self.images)))
            self.files = fileRows
            return True
        except Exception:
            return False




class Downloader(multiprocessing.Process):
    """
    Class to handle downloading the things we have found to get.
    """

    def __init__(self, thing_queue, download_directory):
        multiprocessing.Process.__init__(self)
        # TODO: add parameters
        self.thing_queue = thing_queue
        self.download_directory = download_directory

    def run(self):
        """ actual download loop.
        """
        while True:
            thing_id = self.thing_queue.get()
            if thing_id is None:
                logging.info("Shutting download queue")
                self.thing_queue.task_done()
                break
            logging.info("Handling id {}".format(thing_id))
            Thing(thing_id).download(self.download_directory)
            self.thing_queue.task_done()
        return


                


class Grouping:
    """ Holds details of a group of things for download
        This is effectively (although not actually) an abstract class
        - use Collection or Designs instead.
    """

    def __init__(self, quick):
        self.things = []
        self.total = 0
        self.req_id = None
        self.last_page = 0
        self.per_page = None
        # Should we stop downloading when we hit a known datestamp?
        self.quick = quick 
        # These should be set by child classes.
        self.url = None
        self.download_dir = None
        self.collection_url = None

    def _get_small_grouping(self, req):
        """ Handle small groupings """
        soup = BeautifulSoup(req.text, features='lxml')
        links = soup.find_all('a', {'class': 'card-img-holder'})
        self.things = [x['href'].split(':')[1] for x in links]
        self.total = len(self.things)

        return self.things

    def get(self):
        """ retrieve the things of the grouping. """
        if self.things:
            # We've already done it.
            return self.things

        # Check for initialisation:
        if not self.url:
            logging.error("No URL set - object not initialised properly?")
            raise ValueError("No URL set - object not initialised properly?")

        # Get the internal details of the grouping.
        logging.debug("Querying {}".format(self.url))
        c_req = requests.get(self.url)
        total = TOTAL_REGEX.search(c_req.text)
        if total is None:
            # This is a small (<13) items grouping. Pull the list from this req.
            return self._get_small_grouping(c_req)
        self.total = total.groups()[0]
        self.req_id = ID_REGEX.search(c_req.text).groups()[0]
        self.last_page = int(LAST_PAGE_REGEX.search(c_req.text).groups()[0])
        self.per_page = PER_PAGE_REGEX.search(c_req.text).groups()[0]
        parameters = {
            'base_url': self.url,
            'page': '1',
            'per_page': '12',
            'id': self.req_id
        }
        for current_page in range(1, self.last_page + 1):
            parameters['page'] = current_page
            req = requests.post(self.collection_url, parameters)
            soup = BeautifulSoup(req.text, features='lxml')
            links = soup.find_all('a', {'class': 'card-img-holder'})
            self.things += [x['href'].split(':')[1] for x in links]

        return self.things

    def download(self):
        """ Downloads all the files in a collection """
        if not self.things:
            self.get()

        if not self.download_dir:
            raise ValueError(
                "No download_dir set - invalidly initialised object?")

        base_dir = os.getcwd()
        try:
            os.mkdir(self.download_dir)
        except FileExistsError:
            logging.info("Target directory {} already exists. Assuming a resume."
                         .format(self.download_dir))
        logging.info("Downloading {} thing(s).".format(self.total))
        for idx, thing in enumerate(self.things):
            logging.info("Downloading thing {} - {}".format(idx, thing))
            RC = Thing(thing).download(self.download_dir)
            if self.quick and RC==State.ALREADY_DOWNLOADED:
                logging.info("Caught up, stopping.")
                return


class Collection(Grouping):
    """ Holds details of a collection. """

    def __init__(self, user, name, directory, quick):
        Grouping.__init__(self, quick)
        self.user = user
        self.name = name
        self.url = "{}/{}/collections/{}".format(
            URL_BASE, self.user, strip_ws(self.name))
        self.download_dir = os.path.join(directory,
                                         "{}-{}".format(slugify(self.user), slugify(self.name)))
        self.collection_url = URL_COLLECTION


class Designs(Grouping):
    """ Holds details of all of a users' designs. """

    def __init__(self, user, directory, quick):
        Grouping.__init__(self, quick)
        self.user = user
        self.url = "{}/{}/designs".format(URL_BASE, self.user)
        self.download_dir = os.path.join(
            directory, "{} designs".format(slugify(self.user)))
        self.collection_url = USER_COLLECTION


class Thing:
    """ An individual design on thingiverse. """

    def __init__(self, thing_id):
        self.thing_id = thing_id
        self.last_time = None
        self._parsed = False
        self._needs_download = True
        self.text = None
        self.title = None
        self.download_dir = None

    def _parse(self, base_dir):
        """ Work out what, if anything needs to be done. """
        if self._parsed:
            return

        url = "{}/thing:{}/files".format(URL_BASE, self.thing_id)
        try:
            BROWSER.get(url)
            wait = WebDriverWait(BROWSER, 60)
            pc = PageChecker()
            wait.until(pc)
        except requests.exceptions.ConnectionError as error:
            logging.error("Unable to connect for thing {}: {}".format(
                self.thing_id, error))
            return
        except selenium.common.exceptions.TimeoutException:
            logging.error(pc.log)
            logging.error("Timeout trying to parse thing {}".format(self.thing_id))
            return

        self.title = pc.title
        self._file_links=[]
        for link in pc.files:
            logging.debug("Parsing link: {}".format(link.text))
            link_link = link.find_element_by_xpath(".//a").get_attribute("href")
            if link_link.endswith("/zip"):
                # bulk link.
                continue
            try:
                link_title, link_details, _ = link.text.split("\n")
            except ValueError:
                # If it is a filetype that doesn't generate a picture, then we get an extra field at the start.
                _, link_title, link_details, _ = link.text.split("\n")
                
            #link_details will be something like '461 kb | Updated 06-11-2019 | 373 Downloads'
            #need to convert from M D Y to Y M D
            link_date = [int(x) for x in link_details.split("|")[1].split()[-1].split("-")]
            try:
                self._file_links.append(FileLink(strip_invalid_chars(link_title), datetime.datetime(link_date[2], link_date[0], link_date[1]), link_link))
            except ValueError:
                logging.error(link_date)

        self._image_links=[x.find_element_by_xpath(".//img").get_attribute("src") for x in pc.images]
        self._license = strip_invalid_chars(pc.license)
        self.pc = pc


        self.old_download_dir = os.path.join(base_dir, slugify(self.title))
        self.download_dir = os.path.join(base_dir, "{} - {}".format(self.thing_id, slugify(self.title)))

        logging.debug("Parsing {} ({})".format(self.thing_id, self.title))

        if not os.path.exists(self.download_dir):
            logging.info("Looking for old dir at {}".format(self.old_download_dir))
            if os.path.exists(self.old_download_dir):
                logging.warning("Found previous style download directory. Moving it from {} to {}".format(self.old_download_dir, self.download_dir))
                os.rename(self.old_download_dir, self.download_dir)
            else:
                # Not yet downloaded
                self._parsed = True
                return

        timestamp_file = os.path.join(self.download_dir, 'timestamp.txt')
        if not os.path.exists(timestamp_file):
            # Old download from before
            logging.warning(
                "Old-style download directory found. Assuming update required.")
            self._parsed = True
            return

        try:
            with open(timestamp_file, 'r') as timestamp_handle:
                # add the .split(' ')[0] to remove the timestamp from the old style timestamps
                last_bits = [int(x) for x in timestamp_handle.readlines()[0].split(' ')[0].split("-")]
                logging.warning(last_bits)
                try:
                    self.last_time = datetime.datetime(last_bits[0], last_bits[1], last_bits[2])
                except ValueError:
                    # This one appears to be M D Y
                    self.last_time = datetime.datetime(last_bits[2], last_bits[0], last_bits[1])

            logging.info("last downloaded version: {}".format(self.last_time))
        except FileNotFoundError:
            # Not run on this thing before.
            logging.info(
                "Old-style download directory found. Assuming update required.")
            self.last_time = None
            self._needs_download = True
            self._parsed = True
            return

        # OK, so we have a timestamp, lets see if there is anything new to get
        for file_link in self._file_links:
            if file_link.last_update > self.last_time:
                logging.info(
                    "Found new/updated file {} - {}".format(file_link.name, file_link.last_update))
                self._needs_download = True
                self._parsed = True
                return

        # Got here, so nope, no new files.
        self._needs_download = False
        self._parsed = True

    def download(self, base_dir):
        """ Download all files for a given thing. 
            Returns True iff the thing is now downloaded (not iff it downloads the thing!)
        """
        if not self._parsed:
            self._parse(base_dir)

        if not self._parsed:
            logging.error(
                "Unable to parse {} - aborting download".format(self.thing_id))
            return State.FAILED

        if not self._needs_download:
            print("{} - {} already downloaded - skipping.".format(self.thing_id, self.title))
            return State.ALREADY_DOWNLOADED

        # Have we already downloaded some things?
        timestamp_file = os.path.join(self.download_dir, 'timestamp.txt')
        prev_dir = None
        if os.path.exists(self.download_dir):
            if not os.path.exists(timestamp_file):
                # edge case: old style dir w/out timestamp.
                logging.warning("Old style download dir found at {}".format(self.title))
                prev_count = 0
                target_dir = "{}_old".format(self.download_dir)
                while os.path.exists(target_dir):
                    prev_count = prev_count + 1
                    target_dir = "{}_old_{}".format(self.download_dir, prev_count)
                os.rename(self.download_dir, target_dir)
            else:
                prev_dir = "{}_{}".format(self.download_dir, slugify(self.last_time.__str__()))
                os.rename(self.download_dir, prev_dir)

        # Get the list of files to download

        new_file_links = []
        old_file_links = []
        new_last_time = None

        if not self.last_time:
            # If we don't have anything to copy from, then it is all new.
            logging.debug("No last time, downloading all files")
            new_file_links = self._file_links
            new_last_time = new_file_links[0].last_update
            
            for file_link in new_file_links:
                new_last_time = max(new_last_time, file_link.last_update)
            logging.debug("New timestamp will be {}".format(new_last_time))
        else:
            new_last_time = self.last_time
            for file_link in self._file_links:
                if file_link.last_update > self.last_time:
                    new_file_links.append(file_link)
                    new_last_time = max(new_last_time, file_link.last_update)
                else:
                    old_file_links.append(file_link)

        logging.debug("new timestamp {}".format(new_last_time))

        # OK. Time to get to work.
        logging.debug("Generating download_dir")
        os.mkdir(self.download_dir)
        filelist_file = os.path.join(self.download_dir, "filelist.txt")
        with open(filelist_file, 'w') as fl_handle:
            for fl in self._file_links:
              base_link = fl.link
              try:
                fl.link=requests.get(fl.link, allow_redirects=False).headers['location']
              except Exception:
                # Sometimes Thingiverse just gives us the direct link the first time. Not sure why.
                pass
              
              fl_handle.write("{},{},{}, {}\n".format(fl.link, fl.name, fl.last_update, base_link))


        # First grab the cached files (if any)
        logging.info("Copying {} unchanged files.".format(len(old_file_links)))
        for file_link in old_file_links:
            old_file = os.path.join(prev_dir, file_link.name)
            new_file = os.path.join(self.download_dir, file_link.name)
            try:
                logging.debug("Copying {} to {}".format(old_file, new_file))
                copyfile(old_file, new_file)
            except FileNotFoundError:
                logging.warning(
                    "Unable to find {} in old archive, redownloading".format(file_link["title"]))
                new_file_links.append(file_link)

        # Now download the new ones
        logging.info("Downloading {} new files of {}".format(
            len(new_file_links), len(self._file_links)))
        try:
            for file_link in new_file_links:
                file_name = os.path.join(self.download_dir, file_link.name)
                logging.debug("Downloading {} from {} to {}".format(
                    file_link.name, file_link.link, file_name))
                data_req = requests.get(file_link.link)
                with open(file_name, 'wb') as handle:
                    handle.write(data_req.content)
        except Exception as exception:
            logging.error("Failed to download {} - {}".format(file_link.name, exception))
            os.rename(self.download_dir, "{}_failed".format(self.download_dir))
            return State.FAILED


        # People like images. But this doesn't work yet.
        image_dir = os.path.join(self.download_dir, 'images')
        logging.info("Downloading {} images.".format(len(self._image_links)))
        try:
            os.mkdir(image_dir)
            for imagelink in self._image_links:
                filename = os.path.basename(imagelink)
                if filename.endswith('stl'):
                    filename = "{}.png".format(filename)
                image_req = requests.get(imagelink)
                with open(os.path.join(image_dir, filename), 'wb') as handle:
                    handle.write(image_req.content)
        except Exception as exception:
            print("Failed to download {} - {}".format(filename, exception))
            os.rename(self.download_dir, "{}_failed".format(self.download_dir))
            return State.FAILED

        """
        # instructions are good too.
        logging.info("Downloading readme")
        try:
            readme_txt = soup.find('meta', property='og:description')[
                'content']
            with open(os.path.join(self.download_dir, 'readme.txt'), 'w') as readme_handle:
                readme_handle.write("{}\n".format(readme_txt))
        except (TypeError, KeyError) as exception:
            logging.warning("No readme? {}".format(exception))
        except IOError as exception:
            logging.warning("Failed to write readme! {}".format(exception))

        """
        # Best get some licenses
        logging.info("Downloading license")
        try:
            if self._license:
                with open(os.path.join(self.download_dir, 'license.txt'), 'w') as license_handle:
                    license_handle.write("{}\n".format(self._license))
        except IOError as exception:
            logging.warning("Failed to write license! {}".format(exception))

        try:
            # Now write the timestamp
            with open(timestamp_file, 'w') as timestamp_handle:
                timestamp_handle.write(new_last_time.__str__())
        except Exception as exception:
            print("Failed to write timestamp file - {}".format(exception))
            os.rename(self.download_dir, "{}_failed".format(self.download_dir))
            return State.FAILED
        self._needs_download = False
        logging.debug("Download of {} finished".format(self.title))
        return State.OK


def do_batch(batch_file, download_dir, quick):
    """ Read a file in line by line, parsing each as a set of calls to this script."""
    with open(batch_file) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                # Skip empty lines
                continue
            logging.info("Handling instruction {}".format(line))
            command_arr = line.split()
            if command_arr[0] == "thing":
                logging.debug(
                    "Handling batch thing instruction: {}".format(line))
                Thing(command_arr[1]).download(download_dir)
                continue
            if command_arr[0] == "collection":
                logging.debug(
                    "Handling batch collection instruction: {}".format(line))
                Collection(command_arr[1], command_arr[2],
                           download_dir, quick).download()
                continue
            if command_arr[0] == "user":
                logging.debug(
                    "Handling batch collection instruction: {}".format(line))
                Designs(command_arr[1], download_dir, quick).download()
                continue
            logging.warning("Unable to parse current instruction. Skipping.")


def main():
    """ Entry point for script being run as a command. """
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log-level", choices=[
                        'debug', 'info', 'warning'], default='info', help="level of logging desired")
    parser.add_argument("-d", "--directory",
                        help="Target directory to download into")
    parser.add_argument("-f", "--log-file",
                        help="Place to log debug information to")
    parser.add_argument("-q", "--quick", action="store_true",
                        help="Assume date ordering on posts")

    subparsers = parser.add_subparsers(
        help="Type of thing to download", dest="subcommand")
    collection_parser = subparsers.add_parser(
        'collection', help="Download one or more entire collection(s)")
    collection_parser.add_argument(
        "owner", help="The owner of the collection(s) to get")
    collection_parser.add_argument(
        "collections", nargs="+",  help="Space seperated list of the name(s) of collection to get")
    thing_parser = subparsers.add_parser(
        'thing', help="Download a single thing.")
    thing_parser.add_argument(
        "things", nargs="*", help="Space seperated list of thing ID(s) to download")
    user_parser = subparsers.add_parser(
        "user",  help="Download all things by one or more users")
    user_parser.add_argument(
        "users", nargs="+", help="A space seperated list of the user(s) to get the designs of")
    batch_parser = subparsers.add_parser(
        "batch", help="Perform multiple actions written in a text file")
    batch_parser.add_argument(
        "batch_file", help="The name of the file to read.")
    subparsers.add_parser("version", help="Show the current version")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(1)
    if not args.directory:
        args.directory = os.getcwd()

    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(args.log_level.upper())

    logger.addHandler(console_handler)
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


    # Start downloader
    thing_queue = multiprocessing.JoinableQueue()
    logging.debug("starting {} downloader(s)".format(DOWNLOADER_COUNT))
    downloaders = [Downloader(thing_queue, args.directory) for _ in range(DOWNLOADER_COUNT)]
    for downloader in downloaders:
        downloader.start()


    if args.subcommand.startswith("collection"):
        for collection in args.collections:
            Collection(args.owner, collection, args.directory, args.quick).download()
    if args.subcommand == "thing":
        for thing in args.things:
            thing_queue.put(thing)
    if args.subcommand == "user":
        for user in args.users:
            Designs(user, args.directory, args.quick).download()
    if args.subcommand == "version":
        print("thingy_grabber.py version {}".format(VERSION))
    if args.subcommand == "batch":
        do_batch(args.batch_file, args.directory, args.quick)

    # Stop the downloader processes
    for downloader in downloaders:
        thing_queue.put(None)

if __name__ == "__main__":    
    multiprocessing.freeze_support()
    main()
