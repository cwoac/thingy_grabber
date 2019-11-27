# thingy_grabber
Script for archiving thingiverse things. Due to this being a glorified webscraper, it's going to be very fragile.

## Usage:
````
usage: thingy_grabber.py [-h] [-v] [-d DIRECTORY] {collection,thing,user,version} ...

positional arguments:
  {collection,thing,user,version}
                        Type of thing to download
    collection          Download an entire collection
    thing               Download a single thing.
    user                Download all things by a user
    version             Show the current version

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Be more verbose
  -d DIRECTORY, --directory DIRECTORY
                        Target directory to download into
````

### Things
`thingy_grabber.py thing thingid`
This will create a directory named after the title of the thing with the given ID and download the files into it.

### Collections
`thingy_grabber.py collection user_name collection_name`
Where `user_name` is the name of the creator of the collection (not nes. your name!) and `collection_name` is the name of the collection you want.

This will create a series of directorys `user-collection/thing-name` for each thing in the collection.

If for some reason a download fails, it will get moved sideways to `thing-name-failed` - this way if you rerun it, it will only reattmpt any failed things.

### User designs
`thingy_grabber.py user_name`
Where `user_name` is the name of a creator.

This will create a series of directories `user designs/thing-name` for each thing that user has designed.

If for some reason a download fails, it will get moved sideways to `thing-name-failed` - this way if you rerun it, it will only reattmpt any failed things.

## Requirements
python3, beautifulsoup4, requests, lxml

## Current features:
- can download an entire collection, creating seperate subdirs for each thing in the collection
- If you run it again with the same settings, it will check for updated files and only update what has changed. This should make it suitible for syncing a collection on a cronjob
- If there is an updated file, the old directory will be moved to `name_timestamp` where `timestamp` is the last upload time of the old files. The code will then copy unchanged files across and download any new ones.


## Todo features (maybe):
- less perfunctory error checking / handling
- attempt to use -failed dirs for resuming
- pull down images as well
