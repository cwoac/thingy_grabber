# thingy_grabber
Script for archiving thingiverse things. Due to this being a glorified webscraper, it's going to be very fragile.

## Usage:
````
thingy_grabber.py [-h] [-v] {collection,thing} ...

positional arguments:
  {collection,thing}  Type of thing to download
    collection        Download an entire collection
    thing             Download a single thing.

optional arguments:
  -h, --help          show this help message and exit
  -v, --verbose       Be more verbose
````
### Things
`thingy_grabber.py thing thingid`
This will create a directory named after the title of the thing with the given ID and download the files into it.


### Collections
`thingy_grabber collection user_name collection_name`
Where `user_name` is the name of the creator of the collection (not nes. your name!) and `collection_name` is the name of the collection you want.

This will create a series of directorys `user-collection/thing-name` for each thing in the collection.

If for some reason a download fails, it will get moved sideways to `thing-name-failed` - this way if you rerun it, it will only reattmpt any failed things.

## Requirements
python3, beautifulsoup4, requests, lxml

## Current features:
- can download an entire collection, creating seperate subdirs for each thing in the collection
- If you run it again with the same settings, it will check for updated files and only update what has changed. This should make it suitible for syncing a collection on a cronjob
CAVEAT: This script will *not delete files*. So if there has been an update and some files have been moved or renamed, they will be mixed in with the old stuff.


## Todo features (maybe):
- download things by designer
- less perfunctory error checking / handling
- attempt to use -failed dirs for resuming
- pull down images as well
- handle old/deleted files on update
