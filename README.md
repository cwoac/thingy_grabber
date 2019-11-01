# thingy_grabber
Script for archiving thingiverse things. Due to this being a glorified webscraper, it's going to be very fragile.

## Usage:
`thingy_grabber.py user_name collection_name`

Where `user_name` is the name of the creator of the collection (not nes. your name!) and `collection_name` is the name of the collection you want.

This will create a series of directorys `user-collection/thing-name` for each thing in the collection.
If a thing's directory already exists, it will be skipped.

If for some reason a download fails, it will get moved sideways to `thing-name-failed` - this way if you rerun it, it will only reattmpt any failed things.

## Requirements
python3, beautifulsoup4, requests, lxml

## Current features:
- can download an entire collection, creating seperate subdirs for each thing in the collection

## Todo features:
- download a single thing
- download things by designer
- less perfunctory error checking / handling
- attempt to use -failed dirs for resuming
- detect updated models and redownload them
