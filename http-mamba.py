"""
Based on:
https://pawelmhm.github.io/asyncio/python/aiohttp/2016/04/22/asyncio-aiohttp.html

Added:
* timings
* params, including reading from file
"""
import argparse
import asyncio
import csv
import time
from itertools import groupby
from urllib.parse import parse_qs

import async_timeout
from aiohttp import ClientSession
from operator import itemgetter


async def fetch(session, timeout, args):
    file_time = args.pop('file_time')
    req_time = time.perf_counter()
    with async_timeout.timeout(timeout, loop=session.loop):
        async with session.request(**args) as response:
            resp_time = time.perf_counter()
            await response.read()
            return {'status': response.status,
                    'file_duration': time.perf_counter() - file_time,
                    'req_duration': time.perf_counter() - req_time,
                    'resp_duration': resp_time - req_time}


async def bound_fetch(sem, session, timeout, args):
    async with sem:
        return await fetch(session, timeout, args)


def read_file(default_method, default_url, default_headers, filename):
    with open(filename) as file:
        reader = csv.DictReader(file)
        for row in reader:
            headers = default_headers.copy()
            headers.update(parse_qs(row.get('headers'), keep_blank_values=True, strict_parsing=False))
            yield {'url': row.get('url', default_url),
                   'method': row.get('method', default_method),
                   'headers': headers,
                   'data': row.get('body', ''),
                   'file_time': time.perf_counter()}


def get_urls(method, url, headers, number):
    for i in range(number):
        yield {'url': url,
               'method': method,
               'headers': headers,
               'data': None,
               'file_time': time.perf_counter()}


async def run(connections, timeout, method, url, headers, number, urls_file):
    tasks = []
    sem = asyncio.Semaphore(connections)

    if urls_file:
        urls = read_file(method, url, headers, urls_file)
    else:
        urls = get_urls(method, url, headers, number)

    async with ClientSession() as session:
        for args in urls:
            task = asyncio.ensure_future(bound_fetch(sem, session, timeout, args))
            tasks.append(task)

        responses = await asyncio.gather(*tasks)

    keyfunc = itemgetter('status')
    for status, group in groupby(sorted(responses, key=keyfunc), keyfunc):
        times = [response['resp_duration'] for response in group]
        print('Status {}: {} responses, avg {:.4f} time'.format(status, len(times), sum(times) / len(times)))

    times = [response['resp_duration'] for response in responses]
    print('Avg time: {:.4f}'.format(sum(times) / len(times)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='HTTP benchmark utility')
    parser.add_argument('-i', '--input', help='read requests from input CSV file with url, method, '
                                              'headers and body columns (both as query string)')
    parser.add_argument('-m', '--method', default='get', help='HTTP method, defaults to GET')
    parser.add_argument('-u', '--url', help='request a single url')
    parser.add_argument('--headers', help='headers written as query string, ie. name=value&name2=value2')
    parser.add_argument('-n', '--num', help='number of request to perform')
    parser.add_argument('-c', '--connections', help='max connections')
    parser.add_argument('-t', '--timeout', default=30, help='single request timeout, defaults to 30 seconds')
    options = parser.parse_args()

    loop = asyncio.get_event_loop()
    future = asyncio.ensure_future(run(int(options.connections), int(options.timeout),
                                       options.method.lower(), options.url, parse_qs(options.headers), int(options.num),
                                       options.input))
    loop.run_until_complete(future)
