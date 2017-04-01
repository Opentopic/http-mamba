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
from urllib.parse import parse_qsl

import async_timeout
from aiohttp import ClientSession
from operator import itemgetter


async def fetch(session, timeout, args):
    file_time = args.pop('file_time')
    req_time = time.perf_counter()
    with async_timeout.timeout(timeout, loop=session.loop):
        async with session.request(**args) as response:
            resp_time = time.perf_counter()
            exception = None
            try:
                await response.read()
            except Exception as e:
                exception = e
            return {'status': response.status,
                    'exception': exception,
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
            headers.update(dict(parse_qsl(row.get('headers'), keep_blank_values=True, strict_parsing=False)))
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

def report(responses):
    keyfunc = itemgetter('status')
    for status, group in groupby(sorted(responses, key=keyfunc), keyfunc):
        times = [response['resp_duration'] for response in group]
        print('Status {}: {} responses, avg {:.4f} time'.format(status, len(times), sum(times) / len(times)))

    times = [response['resp_duration'] for response in responses]
    print('Avg time: {:.4f}'.format(sum(times) / len(times)))


async def run(connections, timeout, method, url, headers, number, urls_file, print_report):
    tasks = []
    responses = []
    sem = asyncio.Semaphore(connections)

    if urls_file:
        urls = read_file(method, url, headers, urls_file)
    else:
        urls = get_urls(method, url, headers, number)

    async with ClientSession() as session:
        for args in urls:
            task = asyncio.ensure_future(bound_fetch(sem, session, timeout, args))
            tasks.append(task)
            if len(tasks) % 1000 == 0:
                responses = await asyncio.gather(*tasks)
                if print_report:
                    report(responses)
                tasks = []

        responses = await asyncio.gather(*tasks)
        if print_report:
            report(responses)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='HTTP benchmark utility')
    parser.add_argument('-i', '--input', help='read requests from input CSV file with url, method, '
                                              'headers and body columns (both as query string)')
    parser.add_argument('-m', '--method', default='get', help='HTTP method, defaults to GET')
    parser.add_argument('-u', '--url', help='request a single url')
    parser.add_argument('--headers', help='headers written as query string, ie. name=value&name2=value2')
    parser.add_argument('-n', '--num', help='number of request to perform')
    parser.add_argument('-c', '--connections', default=10, help='max simultaneous connections, defaults to 10')
    parser.add_argument('-t', '--timeout', default=30, help='single request timeout, defaults to 30 seconds')
    parser.add_argument('-r', '--report', default=False, help='should a report be generated')
    options = parser.parse_args()

    loop = asyncio.get_event_loop()
    if options.num is not None:
        options.num = int(options.num)
    headers = dict(parse_qsl(options.headers))
    future = asyncio.ensure_future(run(int(options.connections), int(options.timeout),
                                       options.method.lower(), options.url, headers,options.num,
                                       options.input, options.report))
    loop.run_until_complete(future)
