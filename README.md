# thingy_grabber
Script for archiving thingiverse things.

## Usage:
````
usage: thingy_grabber.py [-h] [-l {debug,info,warning}] [-d DIRECTORY] [-f LOG_FILE] [-q] [-c] [-a API_KEY]
                         {collection,thing,user,batch,version} ...

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
  -c, --compress        Compress files
  -a API_KEY, --api-key API_KEY
                        API key for thingiverse
````

## API KEYs
Thingy_grabber v0.10.0 accesses thingiverse in a _substantially_ different way to before. The plus side is it should be more reliable, possibly faster and no longer needs selenium or a firefox instance (and so drastically reduces memory overhead). The downside is you are _going_ to have to do something to continue using the app - basically get yourself an API KEY.

To do this, go to https://www.thingiverse.com/apps/create and create your own selecting Desktop app.
Once you have your key, either specify it on the command line or put it in a text file called `api.key` whereever you are running the script from - the script will auto load it.

### Why can't I use yours? 
Because API keys can (are?) rate limited.

## Downloads
The latest version can be downloaded from here: https://github.com/cwoac/thingy_grabber/releases/.  Under the 'assets' triangle there is precompiled binaries for windows (no python needed!).

## Docker
You can run thingy_grabber from a container

```
docker build -t thingy_grabber .
docker run --rm -v $PWD:/things thingy_grabber -a YOURAPIKEY -d /things user cwoac
```

## Getting started
First download the code. Either grab the source, or get the windows binary from above and extract it somewhere. If you are running from source, see `requirements.yaml` for the packages you need. You will also need an API key (as above) and to make a directory to store your downloads in.

oh, and you need to know what you want to download, ofc. It can be either things, collections or just the designs of a user.
once you have done all this you need to open a command prompt and run it.

Let's say you are running windows and using the precompiled binary and extracted the release to the `thingy_grabber` directory on your desktop and you made a `things` directory in your `Documents` directory. 
When you open the command window, it will start in your home directory (say `c:\Users\cwoac`)
`cd Desktop\thingy_grabber` to get to `c:\Users\cwoac\Desktop\thingy_grabber` and check that you are right by trying to run `thingy_grabber` - you should get a long list of possible command line options that looks a lot like the list further up. 
Supposing you want to download all of my stuff (for some crazy reason), then the command will look like this

`thingy_grabber -a YOURAPIKEY -d "c:\Users\cwoac\Documents\things" -c user cwoac`

The `-c` will cause the script to compress the download to a 7z file to save space. If you prefer to leave it uncompressed, just omit the `-c`
That's the basics. Well, acutally, there isn't much more than that to be honest. There is a batch mode so if you create a text file with a list of lines like
```
user cwoac
user solutionlesn
collection cwoac at2018
```
then you can use the `batch` target to run each of these in turn. If you run it a second time with the same options it will only download things which have changed or been added.

## Modes
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
python3, requests, py7xr (>=0.8.2)

## Current features:
- can download an entire collection, creating seperate subdirs for each thing in the collection
- If you run it again with the same settings, it will check for updated files and only update what has changed. This should make it suitible for syncing a collection on a cronjob
- If there is an updated file, the old directory will be moved to `name_timestamp` where `timestamp` is the last upload time of the old files. The code will then copy unchanged files across and download any new ones.

## Changelog
* v0.10.5
  - Fixed handling users with >30 things (thanks Clinton).
  - Added standard contrib and code of conduct files.
* v0.10.4
  - Readme.txt files are now text files, not HTML files.
  - removed some debug print statements that I forgot to remove from the last release (oops).
* v0.10.3
  - Handle trailing whitespace in thing names
  - Fix raw thing grabbing
* v0.10.2
  - Fixed regression in rest API
* v0.10.1
  - A couple of minor bug fixes on exception handling.
* v0.10.0
  - API access! new -a option to provide an API key for more stable access.
* v0.9.0
  - Compression! New -c option will use 7z to create an archival copy of the file once downloaded. 
    Note that although it will use the presence of 7z files to determine if a file has been updated, it currently _won't_ read old files from inside the 7z for handling updates, resulting in marginally larger bandwidth usage when dealing with partially updated things. This will be fixed later.
  - Internal tidying of how old directories are handled - I've tested this fairly heavily, but do let me know if there are issues.
* v0.8.7
  - Always, Always generate a valid time stamp.
* v0.8.6
  - Handle thingiverse returning no files for a thing gracefully.
* v0.8.5
  - Strip '.'s from the end of filenames
  - If you fail a download for an already failed download it no longer throws an exception
  - Truncates paths that are too long for windows
* v0.8.4
  - Just use unicode filenames - puts the unicode characters back in!
  - Force selenium to shutdown firefox on assert and normal exit
* v0.8.3
  - Strip unicode characters from license text
* v0.8.2
  - Strip unicode characters from filenames
* v0.8.1
  - Fix bug on when all files were created / updated in October after the 9th.
* v0.8.0
  - Updated to support new thingiverse front end
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

