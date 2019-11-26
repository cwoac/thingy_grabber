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
from bs4 import BeautifulSoup

URL_BASE = "https://www.thingiverse.com"
URL_COLLECTION = URL_BASE + "/ajax/thingcollection/list_collected_things"

ID_REGEX = re.compile(r'"id":(\d*),')
TOTAL_REGEX = re.compile(r'"total":(\d*),')
LAST_PAGE_REGEX = re.compile(r'"last_page":(\d*),')
# This appears to be fixed at 12, but if it changes would screw the rest up.
PER_PAGE_REGEX = re.compile(r'"per_page":(\d*),')
NO_WHITESPACE_REGEX = re.compile(r'[-\s]+')

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
    """ Holds details of a group of things. """
    def __init__(self):
        self.things = []
        self.total = 0
        self.req_id = None
        self.last_page = 0
        self.per_page = None
        # These two should be set by child classes.
        self.url = None
        self.download_dir = None

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
            req = requests.post(URL_COLLECTION, parameters)
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
            print("Target directory {} already exists. Assuming a resume.".format(self.download_dir))
        os.chdir(self.download_dir)
        for thing in self.things:
            download_thing(thing)
        os.chdir(base_dir)

class Collection(Grouping):
    """ Holds details of a collection. """
    def __init__(self, user, name):
        Grouping.__init__(self)
        self.user = user
        self.name = name
        self.url = "{}/{}/collections/{}".format(URL_BASE, self.user, strip_ws(self.name))
        self.download_dir = os.path.join(os.getcwd(), "{}-{}".format(slugify(self.user), slugify(self.name)))

class Designs(Grouping):
    """ Holds details of all of a users' designs. """
    def __init__(self, user):
        Grouping.__init__(self)
        self.user = user
        self.url = "{}/{}/designs".format(URL_BASE, self.user)
        self.download_dir = os.path.join(os.getcwd(), "{} designs".format(slugify(self.user)))

def download_thing(thing):
    """ Downloads all the files for a given thing. """
    file_url = "{}/thing:{}/files".format(URL_BASE, thing)
    file_req = requests.get(file_url)
    file_soup = BeautifulSoup(file_req.text, features='lxml')

    title = slugify(file_soup.find_all('h1')[0].text.strip())
    base_dir = os.getcwd()
    try:
        os.mkdir(title)
    except FileExistsError:
        pass

    print("Downloading {} ({})".format(thing, title))
    os.chdir(title)
    last_time = None

    try:
        with open('timestamp.txt', 'r') as timestamp_handle:
            last_time = timestamp_handle.readlines()[0]
        if VERBOSE:
            print("last downloaded version: {}".format(last_time))
    except FileNotFoundError:
        # Not run on this thing before.
        if VERBOSE:
            print('Directory for thing already exists, checking for update.')
        last_time = None

    file_links = file_soup.find_all('a', {'class':'file-download'})
    new_last_time = last_time
    new_file_links = []

    for file_link in file_links:
        timestamp = file_link.find_all('time')[0]['datetime']
        if VERBOSE:
            print("Checking {} (updated {})".format(file_link["title"], timestamp))
        if not last_time or timestamp > last_time:
            new_file_links.append(file_link)
        if not new_last_time or timestamp > new_last_time:
            new_last_time = timestamp

    if last_time and new_last_time <= last_time:
        print("Thing already downloaded. Skipping.")
    files = [("{}{}".format(URL_BASE, x['href']), x["title"]) for x in new_file_links]

    try:
        for url, name in files:
            if VERBOSE:
                print("Downloading {} from {}".format(name, url))
            data_req = requests.get(url)
            with open(name, 'wb') as handle:
                handle.write(data_req.content)
        # now write timestamp
        with open('timestamp.txt', 'w') as timestamp_handle:
            timestamp_handle.write(new_last_time)
    except Exception as exception:
        print("Failed to download {} - {}".format(name, exception))
        os.chdir(base_dir)
        os.rename(title, "{}_failed".format(title))
        return


    os.chdir(base_dir)

def main():
    """ Entry point for script being run as a command. """
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="Be more verbose", action="store_true")
    subparsers = parser.add_subparsers(help="Type of thing to download", dest="subcommand")
    collection_parser = subparsers.add_parser('collection', help="Download an entire collection")
    collection_parser.add_argument("owner", help="The owner of the collection to get")
    collection_parser.add_argument("collection", help="The name of the collection to get")
    thing_parser = subparsers.add_parser('thing', help="Download a single thing.")
    thing_parser.add_argument("thing", help="Thing ID to download")
    user_parser = subparsers.add_parser("user", help="Download all things by a user")
    user_parser.add_argument("user", help="The user to get the designs of")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        sys.exit(1)
    global VERBOSE
    VERBOSE = args.verbose
    if args.subcommand.startswith("collection"):
        collection = Collection(args.owner, args.collection)
        print(collection.get())
        collection.download()
    if args.subcommand == "thing":
        download_thing(args.thing)
    if args.subcommand == "user":
        designs = Designs(args.user)
        print(designs.get())
        designs.download()



if __name__ == "__main__":
    main()
