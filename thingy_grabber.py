#!/usr/bin/env python3
"""
Thingiverse bulk downloader
"""

import re
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

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    value = str(re.sub(r'[^\w\s-]', '', value).strip())
    value = str(re.sub(r'[-\s]+', '-', value))
    return value

class Collection:
    """ Holds details of a collection. """
    def __init__(self, user, name):
        self.user = user
        self.name = name
        self.things = []
        self.total = 0
        self.req_id = None
        self.last_page = 0
        self.per_page = None

    def _get_small_collection(self, req):
        """ Handle small collections """
        soup = BeautifulSoup(req.text, features='lxml')
        links = soup.find_all('a', {'class':'card-img-holder'})
        self.things = [x['href'].split(':')[1] for x in links]

        return self.things

    def get_collection(self):
        """ retrieve the things of the collection. """
        if self.things:
            # We've already done it.
            return self.things

        # Get the internal details of the collection.
        c_url = "{}/{}/collections/{}".format(URL_BASE, self.user, self.name)
        c_req = requests.get(c_url)
        total = TOTAL_REGEX.search(c_req.text)
        if total is None:
            # This is a small (<13) items collection. Pull the list from this req.
            return self._get_small_collection(c_req)
        self.total = total.groups()[0]
        self.req_id = ID_REGEX.search(c_req.text).groups()[0]
        self.last_page = int(LAST_PAGE_REGEX.search(c_req.text).groups()[0])
        self.per_page = PER_PAGE_REGEX.search(c_req.text).groups()[0]
        parameters = {
            'base_url':"{}/collections/{}".format(self.user, self.name),
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
            self.get_collection()
        base_dir = os.getcwd()
        new_dir = "{}-{}".format(slugify(self.user), slugify(self.name))
        target_dir = os.path.join(base_dir, new_dir)
        try:
            os.mkdir(target_dir)
        except FileExistsError:
            print("Target directory {} already exists. Assuming a resume.".format(new_dir))
        os.chdir(target_dir)
        for thing in self.things:
            download_thing(thing)


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
        print("Directory for {} ({}) already exists, skipping".format(thing, title))
        return
    print("Downloading {} ({})".format(thing, title))
    os.chdir(title)

    file_links = file_soup.find_all('a', {'class':'file-download'})
    files = [("{}{}".format(URL_BASE, x['href']), x["title"]) for x in file_links]

    for url, name in files:
        data_req = requests.get(url)
        with open(name, 'wb') as handle:
            handle.write(data_req.content)
    os.chdir(base_dir)

def main():
    """ Entry point for script being run as a command. """
    parser = argparse.ArgumentParser()
    parser.add_argument("owner", help="The owner of the collection to get")
    parser.add_argument("collection", help="The name of the collection to get")
    args = parser.parse_args()

    collection = Collection(args.owner, args.collection)
    print(collection.get_collection())
    collection.download()

if __name__ == "__main__":
    main()
