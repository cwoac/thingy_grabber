# thingy_grabber
Script for archiving thingiverse things. Due to this being a glorified webscraper, it's going to be very fragile.

## Usage:
````
usage: thingy_grabber.py [-h] [-l {debug,info,warning}] [-d DIRECTORY] [-f LOG_FILE] [-q] {collection,thing,user,batch,version} ...

positional arguments:
  {collection,thing,user,batch,version}
                        Type of thing to download
    collection          Download one or more entire collection(s)
    thing               Download a single thing.
    user                Download all things by one or more users
    batch               Perform multiple actions written in a text file
    version             Show the current version

optional arguments:
  -h, --help            show this help message and exit
  -l {debug,info,warning}, --log-level {debug,info,warning}
                        level of logging desired
  -d DIRECTORY, --directory DIRECTORY
                        Target directory to download into
  -f LOG_FILE, --log-file LOG_FILE
                        Place to log debug information to
  -q, --quick           Assume date ordering on posts
````

### Things
`thingy_grabber.py thing thingid1 thingid2 ...`
This will create a directory named after the title of the thing(s) with the given ID(s) and download the files into it.

### Collections
`thingy_grabber.py  collection user_name collection_name1 collection_name2`
Where `user_name` is the name of the creator of the collection (not nes. your name!) and `collection_name1...etc` are the name(s) of the collection(s) you want.

This will create a series of directorys `user-collection/thing-name` for each thing in the collection.

If for some reason a download fails, it will get moved sideways to `thing-name-failed` - this way if you rerun it, it will only reattmpt any failed things.

### User designs
`thingy_grabber.py user user_name1, user_name2..`
Where `user_name1.. ` are the names of creator.

This will create a series of directories `user designs/thing-name` for each thing that user has designed.

If for some reason a download fails, it will get moved sideways to `thing-name-failed` - this way if you rerun it, it will only reattmpt any failed things.

### Batch mode
`thingy_grabber.py batch batch_file`
This will load a given text file and parse it as a series of calls to this script. The script should be of the form `command arg1 ...`.
Be warned that there is currently NO validation that you have given a correct set of commands!

An example:
````
thing 3670144
collection cwoac bike
user cwoac
````

If you are using linux, you can just add an appropriate call to the crontab. If you are using windows, it's a bit more of a faff, but at least according to [https://www.technipages.com/scheduled-task-windows](this link), you should be able to with a command something like this (this is not tested!): `schtasks /create /tn thingy_grabber /tr "c:\path\to\thingy_grabber.py -d c:\path\to\output\directory batch c:\path\to\batchfile.txt" /sc weekly /d wed /st 13:00:00`
You may have to play with the quotation marks to make that work though.

### Quick mode
All modes now support 'quick mode' (`-q`), although this has no effect for individual item downloads. As thingyverse sorts it's returned items in descending last modified order (I believe), once we have determined that we have the most recent version of a given thing in a collection, we can safely stop processing that collection as we should have _all_ the remaining items in it already. This _substantially_ speeds up the process of keeping big collections up to date and will noticably reduce the server load it generates.

*Warning:* As it stops as soon as it finds an uptodate successful model, if you have unfixed failed downloads further down the list (for want of a better term), they will _not_ be retried.

*Warning:* At the moment I have not conclusively proven to myself that the result is ordered by last updated and not upload time. Once I have verified this, I will probably be making this the default option.

## Examples
`thingy_grabber.py collection cwoac bike`
Download the collection 'bike' by the user 'cwoac'
`thingy_grabber.py -d downloads -l warning thing 1234 4321 1232`
Download the three things 1234, 4321 and 1232 into the directory downloads. Only give warnings.
`thingy_grabber.py -d c:\downloads -l debug user jim bob`
Download all designs by jim and bob into directories under `c:\downloads`, give lots of debug messages
`

## Requirements
python3, beautifulsoup4, requests, lxml

## Current features:
- can download an entire collection, creating seperate subdirs for each thing in the collection
- If you run it again with the same settings, it will check for updated files and only update what has changed. This should make it suitible for syncing a collection on a cronjob
- If there is an updated file, the old directory will be moved to `name_timestamp` where `timestamp` is the last upload time of the old files. The code will then copy unchanged files across and download any new ones.

## Changelog
* v0.7.0
  - Add new quick mode that stops once it has 'caught up' for a group
* v0.6.3
  - Caught edge case involving old dir clashes
  - Add support for seperate log file
* v0.6.2
  - Added catches for 404s, 504s and malformed pages
* v0.6.1
  - now downloads readme.txt and licence details
* v0.6.0
  - added support for downloading multiple things/design sets/collections from the command line
* v0.5.0
  - better logging options
  - batch mode
* v0.4.0
  - Added a changelog
  - Now download associated images
  - support `-d` to specify base download directory 

## Todo features (maybe):
- attempt to use -failed dirs for resuming
- gui?

