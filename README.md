http-mamba
==========

HTTP benchmarking utility in Python 3 using aiohttp.

It can read a CSV file with urls to request, together with headers and data.

## Requirements

The only requirement is the _aiohttp_ Python 3 library.

## Usage

Example usage:

```
cat << EOF > /tmp/urls.csv
url,headers
http://google.com,Referer=http%3A%2F%2Fgoogle.pl&User-Agent=Mozilla%2F5.0+%28Macintosh%3B+Intel+Mac+OS+X+10_19_5%29
EOF
# this uses 12 concurrent connections without any timeout and writes out a report with avg timing
python http-mamba.py -i /tmp/urls.csv -r -c 12 -t 0
```

For a description of possible switches:

```
python http-mamba.py -h
```

Without an input file, required number of requests will be generated from supplied arguments like url, headers.

With an input file, arguments like headers are used as a default value for all requests
where each single request can override or expand them in the file.
