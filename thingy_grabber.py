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
from dataclasses import dataclass
import py7zr
import glob
import shutil
from io import StringIO
from html.parser import HTMLParser

SEVENZIP_FILTERS = [{'id': py7zr.FILTER_LZMA2}]

# I don't think this is exported by datetime
DEFAULT_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
# Windows cannot handle : in filenames
SAFE_DATETIME_FORMAT = '%Y-%m-%d %H.%M.%S'

API_BASE = "https://api.thingiverse.com"
ACCESS_QP = "access_token={}"
PAGE_QP = "page={}"
API_USER_DESIGNS = API_BASE + "/users/{}/things/?" + ACCESS_QP
API_USER_COLLECTIONS = API_BASE + "/users/{}/collections/all?" + ACCESS_QP
API_USER_LIKES = API_BASE + "/users/{}/likes/?" + ACCESS_QP

# Currently useless as it gives the same info as the matching element in API_USER_COLLECTIONS
API_COLLECTION = API_BASE + "/collections/{}/?" + ACCESS_QP
API_COLLECTION_THINGS = API_BASE + "/collections/{}/things/?" + ACCESS_QP

API_THING_DETAILS = API_BASE + "/things/{}/?" + ACCESS_QP
API_THING_FILES = API_BASE + "/things/{}/files/?" + ACCESS_QP
API_THING_IMAGES = API_BASE + "/things/{}/images/?" + ACCESS_QP
API_THING_DOWNLOAD = "/download/?" + ACCESS_QP

DOWNLOADER_COUNT = 1
RETRY_COUNT = 3

MAX_PATH_LENGTH = 250

VERSION = "0.10.5"

TIMESTAMP_FILE = "timestamp.txt"

SESSION = requests.Session()


class MLStripper(HTMLParser):
    """ Turns HTML markup into plain text
    """

    def error(self, message):
        raise ValueError(message)

    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, d):
        self.text.write(d)

    def get_data(self):
        return self.text.getvalue()

    @staticmethod
    def strip_tags(html):
        s = MLStripper()
        s.feed(html)
        return s.get_data()


@dataclass
class ThingLink:
    thing_id: str
    name: str
    api_link: str


@dataclass
class FileLink:
    name: str
    last_update: datetime.datetime
    link: str


@dataclass
class ImageLink:
    name: str
    link: str


class FileLinks:
    def __init__(self, initial_links=None):
        if initial_links is None:
            initial_links = []
        self.links = []
        self.last_update = None
        for link in initial_links:
            self.append(link)

    def __iter__(self):
        return iter(self.links)

    def __getitem__(self, item):
        return self.links[item]

    def __len__(self):
        return len(self.links)

    def append(self, link):
        try:
            self.last_update = max(self.last_update, link.last_update)
        except TypeError:
            self.last_update = link.last_update
        self.links.append(link)


class State(enum.Enum):
    OK = enum.auto()
    FAILED = enum.auto()
    ALREADY_DOWNLOADED = enum.auto()


def sanitise_url(url):
    """ remove api keys from an url
    """
    return re.sub(r'access_token=\w*',
                  'access_token=***',
                  url)


def strip_time(date_obj):
    """ Takes a datetime object and returns another with the time set to 00:00
    """
    return datetime.datetime.combine(date_obj.date(), datetime.time())


def rename_unique(dir_name, target_dir_name):
    """ Move a directory sideways to a new name, ensuring it is unique.
    """
    target_dir = target_dir_name
    inc = 0
    while os.path.exists(target_dir):
        target_dir = "{}_{}".format(target_dir_name, inc)
        inc += 1
    os.rename(dir_name, target_dir)
    return target_dir


def fail_dir(dir_name):
    """ When a download has failed, move it sideways.
    """
    return rename_unique(dir_name, "{}_failed".format(dir_name))


def truncate_name(file_name):
    """ Ensure the filename is not too long for, well windows basically.
    """
    path = os.path.abspath(file_name)
    if len(path) <= MAX_PATH_LENGTH:
        return path
    base, extension = os.path.splitext(path)
    inc = 0
    new_path = "{}_{}{}".format(base, inc, extension)
    while os.path.exists(new_path):
        new_path = "{}_{}{}".format(base, inc, extension)
        inc += 1
    return new_path


def slugify(value):
    """
    Normalise string, removes invalid for filename charactersr
    and converts string to lowercase.
    """
    logging.debug("Sluggyfying {}".format(value))
    value = unicodedata.normalize('NFKC', value).lower().strip()
    value = re.sub(r'[\\/<>:?*|"]', '', value)
    value = re.sub(r'\.*$', '', value)
    return value.strip()


class Downloader(multiprocessing.Process):
    """
    Class to handle downloading the things we have found to get.
    """

    def __init__(self, thing_queue, download_directory, compress, api_key):
        multiprocessing.Process.__init__(self)
        # TODO: add parameters
        self.thing_queue = thing_queue
        self.download_directory = download_directory
        self.compress = compress
        self.api_key = api_key

    def run(self):
        """ actual download loop.
        """
        while True:
            thing_id = self.thing_queue.get()
            if thing_id is None:
                logging.info("Shutting download queue")
                self.thing_queue.task_done()
                break
            thing = None
            if isinstance(thing_id, str):
                thing = Thing.from_thing_id(thing_id)
            if isinstance(thing_id, ThingLink):
                thing = Thing(thing_id)
            if not thing:
                logging.error("Don't know how to handle thing_id {}".format(thing_id))
            else:
                logging.info("Handling id {}".format(thing_id))
                thing.download(self.download_directory, self.compress, self.api_key)
            self.thing_queue.task_done()
        return


class Grouping:
    """ Holds details of a group of things for download
        This is effectively (although not actually) an abstract class
        - use Collection or Designs instead.
    """

    def __init__(self, quick, compress, api_key):
        self.things = []
        self.total = 0
        self.req_id = None
        self.last_page = 0
        self.per_page = None
        # Should we stop downloading when we hit a known datestamp?
        self.quick = quick
        self.compress = compress
        self.api_key = api_key
        # These should be set by child classes.
        self.url = None
        self.download_dir = None

    @property
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
        logging.debug("Querying {}".format(sanitise_url(self.url)))

        # follow next links until all items are found
        current_url = self.url
        while current_url != None:
            logging.info("requesting:{}".format(sanitise_url(current_url)))
            current_req = SESSION.get(current_url)
            current_url = current_req.links.get('next', {}).get('url')
            if current_req.status_code != 200:
                logging.error(
                    "Got unexpected code {} from url {}: {}".format(current_req.status_code, sanitise_url(self.url),
                                                                    current_req.text))
            else:
                current_json = current_req.json()
                for thing in current_json:
                    logging.debug(thing)
                    self.things.append(ThingLink(thing['id'], thing['name'], thing['url']))
        logging.info("Found {} things.".format(len(self.things)))
        return self.things

    def download(self):
        """ Downloads all the files in a collection """
        if not self.things:
            self.get

        if not self.download_dir:
            raise ValueError(
                "No download_dir set - invalidly initialised object?")

        try:
            os.mkdir(self.download_dir)
        except FileExistsError:
            logging.info("Target directory {} already exists. Assuming a resume."
                         .format(self.download_dir))
        logging.info("Downloading {} thing(s).".format(self.total))
        for idx, thing in enumerate(self.things):
            logging.info("Downloading thing {} - {}".format(idx, thing))
            return_code = Thing(thing).download(self.download_dir, self.compress, self.api_key)
            if self.quick and return_code == State.ALREADY_DOWNLOADED:
                logging.info("Caught up, stopping.")
                return


class Collection(Grouping):
    """ Holds details of a collection. """

    def __init__(self, user, name, directory, quick, compress, api_key):
        Grouping.__init__(self, quick, compress, api_key)
        self.user = user
        self.name = name
        self.paginated = False
        # need to figure out the the ID for the collection
        collection_url = API_USER_COLLECTIONS.format(user, api_key)
        try:
            current_req = SESSION.get(collection_url)
        except requests.exceptions.ConnectionError as error:
            logging.error("Unable to connect for collections for user {}: {}".format(
                self.user, error))
            return
        if current_req.status_code != 200:
            logging.error(
                "Got unexpected code {} from url {}: {}".format(current_req.status_code, sanitise_url(collection_url),
                                                                current_req.text))
            return
        collection_list = current_req.json()
        try:
            # case insensitive to retain parity with previous behaviour
            collection = [x for x in collection_list if x['name'].casefold() == name.casefold()][0]
        except IndexError:
            logging.error("Unable to find collection {} for user {}".format(name, user))
            return
        self.collection_id = collection['id']
        self.url = API_COLLECTION_THINGS.format(self.collection_id, api_key)

        self.download_dir = os.path.join(directory,
                                         "{}-{}".format(slugify(self.user), slugify(self.name)))


class Designs(Grouping):
    """ Holds details of all of a users' designs. """

    def __init__(self, user, directory, quick, compress, api_key):
        Grouping.__init__(self, quick, compress, api_key)
        self.user = user
        self.url = API_USER_DESIGNS.format(user, api_key)
        self.download_dir = os.path.join(
            directory, "{} designs".format(slugify(self.user)))

class Likes(Grouping):
    """ Holds details of all of a users' liked things. """

    def __init__(self, user, directory, quick, compress, api_key):
        Grouping.__init__(self, quick, compress, api_key)
        self.user = user
        self.url = API_USER_LIKES.format(user, api_key)
        self.download_dir = os.path.join(
            directory, "{} likes".format(slugify(self.user)))

class Thing:
    """ An individual design on thingiverse. """

    def __init__(self, thing_link):
        self.thing_id = thing_link.thing_id
        self.name = thing_link.name
        self.last_time = None
        self._parsed = False
        self._needs_download = True
        self.text = None
        self.download_dir = None
        self.time_stamp = None
        self._file_links = FileLinks()
        self._image_links = []

    @classmethod
    def from_thing_id(cls, thing_id):
        """
        Factory method that looks up a thing by ID and creates a Thing object for it
        :param thing_id: to look up
        :return: Thing or None
        """
        return Thing(ThingLink(thing_id, "", ""))

    def _parse(self, base_dir, api_key):
        """ Work out what, if anything needs to be done. """
        if self._parsed:
            return

        # First get the broad details
        url = API_THING_DETAILS.format(self.thing_id, api_key)
        try:
            current_req = SESSION.get(url)
        except requests.exceptions.ConnectionError as error:
            logging.error("Unable to connect for thing {}: {}".format(
                self.thing_id, error))
            return
        # Check for DMCA
        if current_req.status_code == 403:
            logging.error("Access to thing {} is forbidden".format(self.thing_id))
            return
        if current_req.status_code != 200:
            logging.error("Got unexpected code {} from url {}: {}".format(current_req.status_code, sanitise_url(url),
                                                                          current_req.text))
            return

        thing_json = current_req.json()
        try:
            self._license = thing_json['license']
        except KeyError:
            logging.warning("No license found for thing {}?".format(self.thing_id))

        details = None
        try:
            details = thing_json['details']
        except KeyError:
            logging.warning("No description found for thing {}?".format(self.thing_id))

        if details:
            try:
                self._details = MLStripper.strip_tags(details)
            except ValueError as e:
                logging.warning("Unable to strip HTML from readme: {}".format(e))
                self._details = details

        if not self.name:
            # Probably generated with factory method.
            try:
                self.name = thing_json['name']
            except KeyError:
                logging.warning("No name found for thing {}?".format(self.thing_id))
                self.name = self.thing_id

        # Now get the file details
        file_url = API_THING_FILES.format(self.thing_id, api_key)

        try:
            current_req = SESSION.get(file_url)
        except requests.exceptions.ConnectionError as error:
            logging.error("Unable to connect for thing {}: {}".format(
                self.thing_id, error))
            return

        if current_req.status_code != 200:
            logging.error("Unexpected status code {} for {}: {}".format(current_req.status_code, sanitise_url(file_url),
                                                                        current_req.text))
            return

        link_list = current_req.json()

        if not link_list:
            logging.error("No files found for thing {} - probably thingiverse being broken, try again later".format(
                self.thing_id))

        for link in link_list:
            logging.debug("Parsing link: {}".format(sanitise_url(link['url'])))
            try:
                datestamp = datetime.datetime.strptime(link['date'], DEFAULT_DATETIME_FORMAT)
                self._file_links.append(
                    FileLink(link['name'], datestamp, link['url'] + API_THING_DOWNLOAD.format(api_key)))
            except ValueError:
                logging.error(link['date'])

        # Finally get the image links
        image_url = API_THING_IMAGES.format(self.thing_id, api_key)

        try:
            current_req = SESSION.get(image_url)
        except requests.exceptions.ConnectionError as error:
            logging.error("Unable to connect for thing {}: {}".format(
                self.thing_id, error))
            return

        if current_req.status_code != 200:
            logging.error(
                "Unexpected status code {} for {}: {}".format(current_req.status_code, sanitise_url(image_url),
                                                              current_req.text))
            return

        image_list = current_req.json()

        if not image_list:
            logging.warning(
                "No images found for thing {} - probably thingiverse being iffy as this seems unlikely".format(
                    self.thing_id))

        for image in image_list:
            logging.debug("parsing image: {}".format(image))
            name = None
            try:
                name = slugify(image['name'])
                # TODO: fallback to other types
                url = [x for x in image['sizes'] if x['type'] == 'display' and x['size'] == 'large'][0]['url']
            except KeyError:
                logging.warning("Missing image for {}".format(name))
            self._image_links.append(ImageLink(name, url))

        self.slug = "{} - {}".format(self.thing_id, slugify(self.name))
        self.download_dir = os.path.join(base_dir, self.slug)

        self._handle_old_directory(base_dir)

        logging.debug("Parsing {} ({})".format(self.thing_id, self.name))
        latest, self.last_time = self._find_last_download(base_dir)

        if not latest:
            # Not yet downloaded
            self._parsed = True
            return

        logging.info("last downloaded version: {}".format(self.last_time))

        # OK, so we have a timestamp, lets see if there is anything new to get
        # First off, are we comparing an old download that threw away the timestamp?
        ignore_time = self.last_time == strip_time(self.last_time)
        try:
            # TODO: Allow for comparison at the exact time
            files_last_update = self._file_links.last_update
            if ignore_time:
                logging.info("Dropping time from comparison stamp as old-style download dir")
                files_last_update = strip_time(files_last_update)

            if files_last_update > self.last_time:
                logging.info(
                    "Found new/updated files {}".format(self._file_links.last_update))
                self._needs_download = True
                self._parsed = True
                return
        except TypeError:
            logging.warning("No files found for {}.".format(self.thing_id))

        # Got here, so nope, no new files.
        self._needs_download = False
        self._parsed = True

    def _handle_old_directory(self, base_dir):
        """ Deal with any old directories from previous versions of the code.
        """
        old_dir = os.path.join(base_dir, slugify(self.name))
        if os.path.exists(old_dir):
            logging.warning("Found old style download_dir. Moving.")
            rename_unique(old_dir, self.download_dir)

    def _handle_outdated_directory(self):
        """ Move the current download directory sideways if the thing has changed.
        """
        if not os.path.exists(self.download_dir):
            # No old directory to move.
            return None
        timestamp_file = os.path.join(self.download_dir, TIMESTAMP_FILE)
        if not os.path.exists(timestamp_file):
            # Old form of download directory
            target_dir_name = "{} - old".format(self.download_dir)
        else:
            target_dir_name = "{} - {}".format(self.download_dir, self.last_time.strftime(SAFE_DATETIME_FORMAT))
        return rename_unique(self.download_dir, target_dir_name)

    def _find_last_download(self, base_dir):
        """ Look for the most recent previous download (if any) of the thing.
        """
        logging.info("Looking for old things")

        # First the DL directory itself.
        timestamp_file = os.path.join(self.download_dir, TIMESTAMP_FILE)

        latest = None
        latest_time = None

        try:
            logging.debug("Checking for existing download in normal place.")
            with open(timestamp_file) as ts_fh:
                timestamp_text = ts_fh.read().strip()
            latest_time = datetime.datetime.strptime(timestamp_text, DEFAULT_DATETIME_FORMAT)
            latest = self.download_dir
        except FileNotFoundError:
            # No existing download directory. huh.
            pass
        except TypeError:
            logging.warning("Invalid timestamp file found in {}".format(self.download_dir))

        # TODO:  Maybe look for old download directories.

        # Now look for 7z files
        candidates = glob.glob(os.path.join(base_dir, "{}*.7z".format(self.thing_id)))
        # +3 to allow for ' - '
        leading_length = len(self.slug) + 3
        for path in candidates:
            candidate = os.path.basename(path)
            try:
                logging.debug("Examining '{}' - '{}'".format(candidate, candidate[leading_length:-3]))
                candidate_time = datetime.datetime.strptime(candidate[leading_length:-3], SAFE_DATETIME_FORMAT)
            except ValueError:
                logging.warning("There was an error finding the date in {}. Ignoring.".format(candidate))
                continue
            try:
                if candidate_time > latest_time:
                    latest_time = candidate_time
                    latest = candidate
            except TypeError:
                latest_time = candidate_time
                latest = candidate
        logging.info("Found last old thing: {} / {}".format(latest, latest_time))
        return latest, latest_time

    def download(self, base_dir, compress, api_key):
        """ Download all files for a given thing. 
            Returns True iff the thing is now downloaded (not iff it downloads the thing!)
        """
        if not self._parsed:
            self._parse(base_dir, api_key)

        if not self._parsed:
            logging.error(
                "Unable to parse {} - aborting download".format(self.thing_id))
            return State.FAILED

        if not self._needs_download:
            logging.info("{} - {} already downloaded - skipping.".format(self.thing_id, self.name))
            return State.ALREADY_DOWNLOADED

        if not self._file_links:
            logging.error(
                "{} - {} appears to have no files. Thingiverse acting up again?".format(self.thing_id, self.name))
            return State.FAILED

        # Have we already downloaded some things?
        renamed_dir = self._handle_outdated_directory()

        # Get the list of files to download

        new_file_links = []
        old_file_links = []
        self.time_stamp = None

        if not self.last_time:
            # If we don't have anything to copy from, then it is all new.
            logging.debug("No last time, downloading all files")
            new_file_links = self._file_links
            self.time_stamp = new_file_links[0].last_update

            for file_link in new_file_links:
                self.time_stamp = max(self.time_stamp, file_link.last_update)
            logging.debug("New timestamp will be {}".format(self.time_stamp))
        else:
            self.time_stamp = self.last_time
            for file_link in self._file_links:
                if file_link.last_update > self.last_time:
                    new_file_links.append(file_link)
                    self.time_stamp = max(self.time_stamp, file_link.last_update)
                else:
                    old_file_links.append(file_link)

        logging.debug("new timestamp {}".format(self.time_stamp))

        # OK. Time to get to work.
        logging.debug("Generating download_dir")
        os.mkdir(self.download_dir)
        filelist_file = os.path.join(self.download_dir, "filelist.txt")
        with open(filelist_file, 'w', encoding="utf-8") as fl_handle:
            for fl in self._file_links:
                fl_handle.write("{},{},{}\n".format(fl.link, fl.name, fl.last_update))

        # First grab the cached files (if any)
        logging.info("Copying {} unchanged files.".format(len(old_file_links)))
        if renamed_dir:
            for file_link in old_file_links:
                try:
                    old_file = os.path.join(renamed_dir, file_link.name)
                    new_file = truncate_name(os.path.join(self.download_dir, file_link.name))
                    logging.debug("Copying {} to {}".format(old_file, new_file))
                    copyfile(old_file, new_file)
                except FileNotFoundError:
                    logging.warning(
                        "Unable to find {} in old archive, redownloading".format(file_link.name))
                    new_file_links.append(file_link)
                except TypeError:
                    # Not altogether sure how this could occur, possibly with some combination of the old file types
                    logging.warning(
                        "Typeerror looking for {} in {}".format(file_link.name, renamed_dir))
                    new_file_links.append(file_link)

        # Now download the new ones
        logging.info("Downloading {} new files of {}".format(
            len(new_file_links), len(self._file_links)))
        try:
            for file_link in new_file_links:
                file_name = truncate_name(os.path.join(self.download_dir, file_link.name))
                logging.debug("Downloading {} from {} to {}".format(
                    file_link.name, file_link.link, file_name))
                data_req = SESSION.get(file_link.link)
                if data_req.status_code != 200:
                    logging.error("Unexpected status code {} for {}".format(data_req.status_code,
                                                                                sanitise_url(file_link.link)))
                    logging.debug("Unexpected status code {} for {}: {}".format(data_req.status_code,
                                                                                sanitise_url(file_link.link),
                                                                                data_req.text))
                    fail_dir(self.download_dir)
                    return State.FAILED

                with open(file_name, 'wb') as handle:
                    handle.write(data_req.content)
        except Exception as exception:
            logging.error("Failed to download {} - {}".format(file_link.name, exception))
            fail_dir(self.download_dir)
            return State.FAILED

        # People like images.
        image_dir = os.path.join(self.download_dir, 'images')
        logging.info("Downloading {} images.".format(len(self._image_links)))
        try:
            os.mkdir(image_dir)
            for imagelink in self._image_links:
                filename = os.path.join(image_dir, imagelink.name)
                image_req = SESSION.get(imagelink.link)
                if image_req.status_code != 200:
                    logging.error("Unexpected status code {} for {}: {}".format(image_req.status_code,
                                                                                sanitise_url(imagelink.link),
                                                                                image_req.text))
                    fail_dir(self.download_dir)
                    return State.FAILED
                with open(truncate_name(filename), 'wb') as handle:
                    handle.write(image_req.content)
        except Exception as exception:
            logging.error("Failed to download {} - {}".format(imagelink.name, exception))
            fail_dir(self.download_dir)
            return State.FAILED

        # Best get some licenses
        logging.info("writing license file")
        try:
            if self._license:
                with open(truncate_name(os.path.join(self.download_dir, 'license.txt')), 'w',
                          encoding="utf-8") as license_handle:
                    license_handle.write("{}\n".format(self._license))
        except IOError as exception:
            logging.warning("Failed to write license! {}".format(exception))

        logging.info("writing readme")
        try:
            if self._details:
                with open(truncate_name(os.path.join(self.download_dir, 'readme.txt')), 'w',
                          encoding="utf-8") as readme_handle:
                    readme_handle.write("{}\n".format(self._details))
        except IOError as exception:
            logging.warning("Failed to write readme! {}".format(exception))

        try:
            # Now write the timestamp
            with open(os.path.join(self.download_dir, TIMESTAMP_FILE), 'w', encoding="utf-8") as timestamp_handle:
                timestamp_handle.write(self.time_stamp.__str__())
        except Exception as exception:
            logging.error("Failed to write timestamp file - {}".format(exception))
            fail_dir(self.download_dir)
            return State.FAILED
        self._needs_download = False
        logging.debug("Download of {} finished".format(self.name))
        if not compress:
            return State.OK

        thing_dir = "{} - {} - {}".format(self.thing_id,
                                          slugify(self.name),
                                          self.time_stamp.strftime(SAFE_DATETIME_FORMAT))
        file_name = os.path.join(base_dir,
                                 "{}.7z".format(thing_dir))
        logging.debug("Compressing {} to {}".format(
            self.name,
            file_name))
        with py7zr.SevenZipFile(file_name, 'w', filters=SEVENZIP_FILTERS) as archive:
            archive.writeall(self.download_dir, thing_dir)
        logging.debug("Compression of {} finished.".format(self.name))
        shutil.rmtree(self.download_dir)
        logging.debug("Removed temporary download dir of {}.".format(self.name))
        return State.OK


def do_batch(batch_file, download_dir, quick, compress, api_key):
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
                Thing.from_thing_id(command_arr[1]).download(download_dir, compress, api_key)
                continue
            if command_arr[0] == "collection":
                logging.debug(
                    "Handling batch collection instruction: {}".format(line))
                Collection(command_arr[1], command_arr[2],
                           download_dir, quick, compress, api_key).download()
                continue
            if command_arr[0] == "user":
                logging.debug(
                    "Handling batch collection instruction: {}".format(line))
                Designs(command_arr[1], download_dir, quick, compress, api_key).download()
                continue
            if command_arr[0] == "likes":
                logging.debug(
                    "Handling batch collection instruction: {}".format(line))
                Likes(command_arr[1], download_dir, quick, compress, api_key).download()
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
    parser.add_argument("-c", "--compress", action="store_true",
                        help="Compress files")
    parser.add_argument("-a", "--api-key",
                        help="API key for thingiverse")

    subparsers = parser.add_subparsers(
        help="Type of thing to download", dest="subcommand")
    collection_parser = subparsers.add_parser(
        'collection', help="Download one or more entire collection(s)")
    collection_parser.add_argument(
        "owner", help="The owner of the collection(s) to get")
    collection_parser.add_argument(
        "collections", nargs="+", help="Space seperated list of the name(s) of collection to get")
    thing_parser = subparsers.add_parser(
        'thing', help="Download a single thing.")
    thing_parser.add_argument(
        "things", nargs="*", help="Space seperated list of thing ID(s) to download")
    user_parser = subparsers.add_parser(
        "user", help="Download all things by one or more users")
    user_parser.add_argument(
        "users", nargs="+", help="A space seperated list of the user(s) to get the designs of")
    likes_parser = subparsers.add_parser(
        "likes", help="Download all things liked by one or more users")
    likes_parser.add_argument(
        "users", nargs="+", help="A space seperated list of the user(s) to get the likes of")
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

    if args.api_key:
        api_key = args.api_key
    else:
        try:
            with open("api.key") as fh:
                api_key = fh.read().strip()
        except Exception as e:
            logging.error("Either specify the api-key on the command line or in a file called 'api.key'")
            logging.error("Exception: {}".format(e))
            return

    logger.addHandler(console_handler)
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Start downloader
    thing_queue = multiprocessing.JoinableQueue()
    logging.debug("starting {} downloader(s)".format(DOWNLOADER_COUNT))
    downloaders = [Downloader(thing_queue, args.directory, args.compress, api_key) for _ in range(DOWNLOADER_COUNT)]
    for downloader in downloaders:
        downloader.start()

    if args.subcommand.startswith("collection"):
        for collection in args.collections:
            Collection(args.owner, collection, args.directory, args.quick, args.compress, api_key).download()
    if args.subcommand == "thing":
        for thing in args.things:
            thing_queue.put(thing)
    if args.subcommand == "user":
        for user in args.users:
            Designs(user, args.directory, args.quick, args.compress, api_key).download()
    if args.subcommand == "likes":
        for user in args.users:
            Likes(user, args.directory, args.quick, args.compress, api_key).download()
    if args.subcommand == "version":
        print("thingy_grabber.py version {}".format(VERSION))
    if args.subcommand == "batch":
        do_batch(args.batch_file, args.directory, args.quick, args.compress, api_key)

    # Stop the downloader processes
    for _ in downloaders:
        thing_queue.put(None)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
