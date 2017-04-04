"""
Based on:
https://pawelmhm.github.io/asyncio/python/aiohttp/2016/04/22/asyncio-aiohttp.html

Added:
* timing and reporting
* params, including reading from file
* disable cookies
"""
import argparse
import asyncio
import csv
import time
from itertools import groupby
from urllib.parse import parse_qsl

import async_timeout
from aiohttp import ClientSession
from aiohttp.abc import AbstractCookieJar
from operator import itemgetter


class NullCookieJar(AbstractCookieJar):
    """A null cookie storage, stores nothing and returns nothing."""

    def __iter__(self):
        raise StopIteration

    def __len__(self):
        return 0

    def clear(self):
        pass

    def update_cookies(self, cookies, response_url=None):
        pass

    def filter_cookies(self, request_url):
        return None


async def fetch(session, timeout, args):
    index = args.pop('index')
    file_time = args.pop('file_time')
    req_time = time.perf_counter()
    with async_timeout.timeout(timeout, loop=session.loop):
        async with session.request(allow_redirects=False, **args) as response:
            resp_time = time.perf_counter()
            exception = None
            body = None
            try:
                body = await response.read()
            except Exception as e:
                exception = e
            return {'index': index,
                    'url': args.get('url'),
                    'status': response.status,
                    'body': body,
                    'exception': exception,
                    'file_duration': time.perf_counter() - file_time,
                    'req_duration': time.perf_counter() - req_time,
                    'resp_duration': resp_time - req_time}


async def bound_fetch(sem, session, timeout, args):
    async with sem:
        return await fetch(session, timeout, args)


def read_file(default_method, default_url, default_headers, filename, number, skip):
    with open(filename) as file:
        reader = csv.DictReader(file)
        i = 0
        for row in reader:
            if skip is not None and i < skip:
                i += 1
                continue
            if number is not None and i >= number - (0 if skip is None else skip):
                break
            headers = default_headers.copy()
            headers.update(dict(parse_qsl(row.get('headers'), keep_blank_values=True, strict_parsing=False)))
            yield {'index': i,
                   'url': row.get('url', default_url),
                   'method': row.get('method', default_method),
                   'headers': headers,
                   'data': row.get('body', ''),
                   'file_time': time.perf_counter()}
            i += 1


def get_urls(method, url, headers, number, skip):
    for i in range(0 if skip is None else skip, number):
        yield {'index': i,
               'url': url,
               'method': method,
               'headers': headers,
               'data': None,
               'file_time': time.perf_counter()}


def report(responses, total_time):
    if not responses:
        return
    print('Last id and url: {} {}'.format(responses[-1]['index'], responses[-1]['url']))
    keyfunc = itemgetter('status')
    for status, group in groupby(sorted(responses, key=keyfunc), keyfunc):
        times = []
        first_response = None
        for response in group:
            times.append(response['resp_duration'])
            if first_response is None:
                first_response = response
        print('Status {}: {} responses, times avg/min/max: {:.4f} / {:.4f} / {:.4f}'.format(
            status, len(times), sum(times) / len(times), min(times), max(times)
        ))
        if int(status) < 200 or 400 <= int(status):
            print('  first url: {}'.format(first_response['url']))
            print('  first body: {}'.format(first_response['body']))

    times = [response['resp_duration'] for response in responses]
    print('Total time: {:.4f}, req/s: {:.4f}, times avg/min/max: {:.4f} / {:.4f} / {:.4f}'.format(
        total_time, len(responses) / total_time, sum(times) / len(times), min(times), max(times)
    ))
    print()


async def run(connections, timeout, method, url, headers, number, skip, urls_file, print_report):
    tasks = []
    sem = asyncio.Semaphore(connections)

    if urls_file:
        urls = read_file(method, url, headers, urls_file, number, skip)
    else:
        urls = get_urls(method, url, headers, number, skip)

    async with ClientSession(cookie_jar=NullCookieJar()) as session:
        warmup_start = time.perf_counter()
        warmup_end = None
        for args in urls:
            task = asyncio.ensure_future(bound_fetch(sem, session, timeout, args))
            tasks.append(task)
            if len(tasks) % (100 * connections) == 0:
                if warmup_end is None and print_report:
                    warmup_end = time.perf_counter()
                    print('Warmup time: {:.4f}'.format(warmup_end - warmup_start))
                    print()
                start_time = time.perf_counter()
                responses = await asyncio.gather(*tasks)
                if print_report:
                    report(responses, time.perf_counter() - start_time)
                tasks = []

        start_time = time.perf_counter()
        responses = await asyncio.gather(*tasks)
        if print_report:
            report(responses, time.perf_counter() - start_time)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='HTTP benchmark utility')
    parser.add_argument('-i', '--input', help='read requests from input CSV file with url, method, '
                                              'headers and body columns (both as query string)')
    parser.add_argument('-m', '--method', default='get', help='HTTP method, defaults to GET')
    parser.add_argument('-u', '--url', help='request a single url')
    parser.add_argument('--headers', help='headers written as query string, ie. name=value&name2=value2')
    parser.add_argument('-n', '--num', help='number of request to perform')
    parser.add_argument('-s', '--skip', help='number of lines from input file to skip')
    parser.add_argument('-c', '--connections', default=10, help='max simultaneous connections, defaults to 10')
    parser.add_argument('-t', '--timeout', default=30, help='single request timeout, defaults to 30 seconds')
    parser.add_argument('-r', '--report', action='store_true', help='should a report be generated')
    options = parser.parse_args()

    loop = asyncio.get_event_loop()
    if options.num is not None:
        options.num = int(options.num)
    if options.skip is not None:
        options.skip = int(options.skip)
    headers = dict(parse_qsl(options.headers))
    future = asyncio.ensure_future(run(int(options.connections), int(options.timeout),
                                       options.method.lower(), options.url, headers, options.num, options.skip,
                                       options.input, options.report))
    loop.run_until_complete(future)
