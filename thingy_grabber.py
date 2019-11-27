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
from shutil import copyfile
from bs4 import BeautifulSoup

URL_BASE = "https://www.thingiverse.com"
URL_COLLECTION = URL_BASE + "/ajax/thingcollection/list_collected_things"
USER_COLLECTION = URL_BASE + "/ajax/user/designs"

ID_REGEX = re.compile(r'"id":(\d*),')
TOTAL_REGEX = re.compile(r'"total":(\d*),')
LAST_PAGE_REGEX = re.compile(r'"last_page":(\d*),')
# This appears to be fixed at 12, but if it changes would screw the rest up.
PER_PAGE_REGEX = re.compile(r'"per_page":(\d*),')
NO_WHITESPACE_REGEX = re.compile(r'[-\s]+')

VERSION = "0.4.0"

VERBOSE = False

def strip_ws(value):
    """ Remove whitespace from a string """
    return str(NO_WHITESPACE_REGEX.sub('-', value))

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    value = str(re.sub(r'[^\w\s-]', '', value).strip())
    value = str(NO_WHITESPACE_REGEX.sub('-', value))
    #value = str(re.sub(r'[-\s]+', '-', value))
    return value

class Grouping:
    """ Holds details of a group of things for download
        This is effectively (although not actually) an abstract class
        - use Collection or Designs instead.
    """
    def __init__(self):
        self.things = []
        self.total = 0
        self.req_id = None
        self.last_page = 0
        self.per_page = None
        # These should be set by child classes.
        self.url = None
        self.download_dir = None
        self.collection_url = None

    def _get_small_grouping(self, req):
        """ Handle small groupings """
        soup = BeautifulSoup(req.text, features='lxml')
        links = soup.find_all('a', {'class':'card-img-holder'})
        self.things = [x['href'].split(':')[1] for x in links]

        return self.things

    def get(self):
        """ retrieve the things of the grouping. """
        if self.things:
            # We've already done it.
            return self.things

        # Check for initialisation:
        if not self.url:
            print("No URL set - object not initialised properly?")
            raise ValueError("No URL set - object not initialised properly?")

        # Get the internal details of the grouping.
        if VERBOSE:
            print("Querying {}".format(self.url))
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
            'base_url':self.url,
            'page':'1',
            'per_page':'12',
            'id':self.req_id
        }
        for current_page in range(1, self.last_page + 1):
            parameters['page'] = current_page
            req = requests.post(self.collection_url, parameters)
            soup = BeautifulSoup(req.text, features='lxml')
            links = soup.find_all('a', {'class':'card-img-holder'})
            self.things += [x['href'].split(':')[1] for x in links]

        return self.things

    def download(self):
        """ Downloads all the files in a collection """
        if not self.things:
            self.get()

        if not self.download_dir:
            raise ValueError("No download_dir set - invalidly initialised object?")

        base_dir = os.getcwd()
        try:
            os.mkdir(self.download_dir)
        except FileExistsError:
            print("Target directory {} already exists. Assuming a resume."
                  .format(self.download_dir))
        if VERBOSE:
            print("Downloading {} things.".format(self.total))
        for thing in self.things:
            Thing(thing).download(self.download_dir)

class Collection(Grouping):
    """ Holds details of a collection. """
    def __init__(self, user, name, directory):
        Grouping.__init__(self)
        self.user = user
        self.name = name
        self.url = "{}/{}/collections/{}".format(
            URL_BASE, self.user, strip_ws(self.name))
        self.download_dir = os.path.join(directory,
                                         "{}-{}".format(slugify(self.user), slugify(self.name)))
        self.collection_url = URL_COLLECTION

class Designs(Grouping):
    """ Holds details of all of a users' designs. """
    def __init__(self, user, directory):
        Grouping.__init__(self)
        self.user = user
        self.url = "{}/{}/designs".format(URL_BASE, self.user)
        self.download_dir = os.path.join(directory, "{} designs".format(slugify(self.user)))
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
        req = requests.get(url)
        self.text = req.text
        soup = BeautifulSoup(self.text, features='lxml')

        print("Found no new files for {}".format(self.title))
        #import code
        #code.interact(local=dict(globals(), **locals()))
        self.title = slugify(soup.find_all('h1')[0].text.strip())
        self.download_dir = os.path.join(base_dir, self.title)

        if not os.path.exists(self.download_dir):
            # Not yet downloaded
            self._parsed = True
            return

        timestamp_file = os.path.join(self.download_dir, 'timestamp.txt')
        if not os.path.exists(timestamp_file):
            # Old download from before
            if VERBOSE:
                print("Old-style download directory found. Assuming update required.")
            self._parsed = True
            return

        try:
            with open(timestamp_file, 'r') as timestamp_handle:
                self.last_time = timestamp_handle.readlines()[0]
            if VERBOSE:
                print("last downloaded version: {}".format(self.last_time))
        except FileNotFoundError:
            # Not run on this thing before.
            if VERBOSE:
                print("Old-style download directory found. Assuming update required.")
            self.last_time = None
            self._parsed = True
            return

        # OK, so we have a timestamp, lets see if there is anything new to get
        file_links = soup.find_all('a', {'class':'file-download'})
        for file_link in file_links:
            timestamp = file_link.find_all('time')[0]['datetime']
            if VERBOSE:
                print("Checking {} (updated {})".format(file_link["title"], timestamp))
            if timestamp > self.last_time:
                print("Found new/updated file {}".format(file_link["title"]))
                self._needs_download = True
                self._parsed = True
                return
        # Got here, so nope, no new files.
        code.interact(local=dict(globals(), **locals()))
        self._needs_download = False
        self._parsed = True

    def download(self, base_dir):
        """ Download all files for a given thing. """
        if not self._parsed:
            self._parse(base_dir)

        if not self._needs_download:
            if VERBOSE:
                print("{} already downloaded - skipping.".format(self.title))
            return

        # Have we already downloaded some things?
        timestamp_file = os.path.join(self.download_dir, 'timestamp.txt')
        prev_dir = None
        if os.path.exists(self.download_dir):
            if not os.path.exists(timestamp_file):
                # edge case: old style dir w/out timestamp.
                print("Old style download dir found for {}".format(self.title))
                os.rename(self.download_dir, "{}_old".format(self.download_dir))
            else:
                prev_dir = "{}_{}".format(self.download_dir, self.last_time)
                os.rename(self.download_dir, prev_dir)

        # Get the list of files to download
        soup = BeautifulSoup(self.text, features='lxml')
        file_links = soup.find_all('a', {'class':'file-download'})

        new_file_links = []
        old_file_links = []
        new_last_time = None

        if not self.last_time:
            # If we don't have anything to copy from, then it is all new.
            new_file_links = file_links
            new_last_time = file_links[0].find_all('time')[0]['datetime']
            for file_link in file_links:
                timestamp = file_link.find_all('time')[0]['datetime']
                if VERBOSE:
                    print("Found file {} from {}".format(file_link["title"], timestamp))
                if timestamp > new_last_time:
                    new_last_time = timestamp
        else:
            for file_link in file_links:
                timestamp = file_link.find_all('time')[0]['datetime']
                if VERBOSE:
                    print("Checking {} (updated {})".format(file_link["title"], timestamp))
                if timestamp > self.last_time:
                    new_file_links.append(file_link)
                else:
                    old_file_links.append(file_link)
                if not new_last_time or timestamp > new_last_time:
                    new_last_time = timestamp

        if VERBOSE:
            print("new timestamp {}".format(new_last_time))

        # OK. Time to get to work.
        os.mkdir(self.download_dir)
        # First grab the cached files (if any)
        for file_link in old_file_links:
            old_file = os.path.join(prev_dir, file_link["title"])
            new_file = os.path.join(self.download_dir, file_link["title"])
            try:
                if VERBOSE:
                    print("Copying {} to {}".format(old_file, new_file))
                copyfile(old_file, new_file)
            except FileNotFoundError:
                print("Unable to find {} in old archive, redownloading".format(file_link["title"]))
                new_file_links.append(file_link)

        # Now download the new ones
        files = [("{}{}".format(URL_BASE, x['href']), x["title"]) for x in new_file_links]
        try:
            for url, name in files:
                file_name = os.path.join(self.download_dir, name)
                if VERBOSE:
                    print("Downloading {} from {} to {}".format(name, url, file_name))
                data_req = requests.get(url)
                with open(file_name, 'wb') as handle:
                    handle.write(data_req.content)
        except Exception as exception:
            print("Failed to download {} - {}".format(name, exception))
            os.rename(self.download_dir, "{}_failed".format(self.download_dir))
            return

        # People like images
        image_dir = os.path.join(self.download_dir, 'images')
        try:
            os.mkdir(image_dir)
            for imagelink in soup.find_all('span', {'class':'gallery-slider'})[0] \
                                 .find_all('div', {'class':'gallery-photo'}):
                url = imagelink['data-full']
                filename = os.path.basename(url)
                if filename.endswith('stl'):
                    filename = "{}.png".format(filename)
                image_req = requests.get(url)
                with open(os.path.join(image_dir, filename), 'wb') as handle:
                    handle.write(image_req.content)
        except Exception as exception:
            print("Failed to download {} - {}".format(filename, exception))
            os.rename(self.download_dir, "{}_failed".format(self.download_dir))
            return




        try:
            # Now write the timestamp
            with open(timestamp_file, 'w') as timestamp_handle:
                timestamp_handle.write(new_last_time)
        except Exception as exception:
            print("Failed to write timestamp file - {}".format(exception))
            os.rename(self.download_dir, "{}_failed".format(self.download_dir))
            return
        self._needs_download = False
        if VERBOSE:
            print("Download of {} finished".format(self.title))

def main():
    """ Entry point for script being run as a command. """
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="Be more verbose", action="store_true")
    parser.add_argument("-d", "--directory", help="Target directory to download into")
    subparsers = parser.add_subparsers(help="Type of thing to download", dest="subcommand")
    collection_parser = subparsers.add_parser('collection', help="Download an entire collection")
    collection_parser.add_argument("owner", help="The owner of the collection to get")
    collection_parser.add_argument("collection", help="The name of the collection to get")
    thing_parser = subparsers.add_parser('thing', help="Download a single thing.")
    thing_parser.add_argument("thing", help="Thing ID to download")
    user_parser = subparsers.add_parser("user", help="Download all things by a user")
    user_parser.add_argument("user", help="The user to get the designs of")
    subparsers.add_parser("version", help="Show the current version")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(1)
    if not args.directory:
        args.directory = os.getcwd()

    global VERBOSE
    VERBOSE = args.verbose
    if args.subcommand.startswith("collection"):
        collection = Collection(args.owner, args.collection, args.directory)
        print(collection.get())
        collection.download()
    if args.subcommand == "thing":
        Thing(args.thing).download(args.directory)
    if args.subcommand == "user":
        designs = Designs(args.user, args.directory)
        print(designs.get())
        designs.download()
    if args.subcommand == "version":
        print("thingy_grabber.py version {}".format(VERSION))

if __name__ == "__main__":
    main()
