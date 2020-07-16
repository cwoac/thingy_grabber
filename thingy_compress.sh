#!/bin/sh
sourcefile=${1%/}

if [ ! -d "$sourcefile" ]
then
    echo "$1 does not appear to be a directory."
    exit 1
fi

timestamp=$(echo $(cat "$sourcefile/timestamp.txt") | sed 's/:/./g')

if [ -z "$timestamp" ]
then
    echo "No timestamp?"
    exit 1
fi

output="${sourcefile} - ${timestamp}.7z"

if [ -f "${output}" ]
then
    echo "Target file ${output} already exists"
    exit 1
fi

7z a -mx=9 "${output}" "${sourcefile}"
