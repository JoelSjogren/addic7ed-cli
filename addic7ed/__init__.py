#!/usr/bin/python2

import os.path
from urlparse import urljoin
from pyquery import PyQuery as query
import requests

import re

last_url = 'http://www.addic7ed.com/'


def get(url, raw=False, **params):
    global last_url
    url = urljoin(last_url, url)
    request = requests.get(url, headers={'Referer': last_url}, params=params)
    last_url = url
    return request.content if raw else query(request.content)


class Episode(object):

    @classmethod
    def search(cls, query):
        links = get('/search.php', search=query, submit='Search')('.tabel a')
        return [cls(link.attrib['href'], link.text) for link in links]

    def __init__(self, url, title=None):
        self.url = url
        self.title = title
        self.versions = []

    def __eq__(self, other):
        return self.url == other.url and self.title == other.title

    def __unicode__(self):
        return self.title

    def __str__(self):
        return unicode(self).encode('utf-8')

    def add_version(self, *args):
        self.versions.append(Version(*args))

    def fetch_versions(self):
        if self.versions:
            return

        result = get(self.url)
        tables = result('.tabel95')
        self.title = tables.find('.titulo').contents()[0].strip()

        for i, table in enumerate(tables[2:-1:2]):
            trs = query(table)('tr')

            release = trs.find('.NewsTitle').text().partition(',')[0]
            release = re.sub('version ', '', release, 0, re.I)

            infos = trs.next().find('.newsDate').eq(0).text()
            infos = re.sub('(?:should)? works? with ', '', infos, 0, re.I)

            for tr in trs[2:]:
                tr = query(tr)
                language = tr('.language')
                if not language:
                    continue

                completeness = language.next().text().partition(' ')[0]
                language = language.text()
                download = tr('a[href*=updated]') or tr('a[href*=original]')
                if not download:
                    continue
                download = download.attr.href
                self.add_version(download, language, release, infos,
                                 completeness)

    def filter_versions(self, languages=[], release=set(), completed=True):
        for version in self.versions:
            version.weight = 0
            version.match_languages(languages)
            version.match_release(release)
            version.match_completeness(completed)

        result = []
        last_weight = None
        for version in sorted(self.versions, key=lambda v: v.weight,
                              reverse=True):
            if last_weight is None:
                last_weight = version.weight
            elif last_weight - version.weight >= 0.5:
                break

            result.append(version)

        result.sort(key=str)
        return result


class Version(object):
    def __init__(self, url, language, release, infos, completeness):
        self.url = url
        self.language = language
        self.release = release
        self.infos = infos
        self.completeness = completeness
        self.release_hash = string_set(infos) | string_set(release)
        self.weight = 0

    def __eq__(self, other):
        return self.url == other.url and self.language == other.language

    def match_languages(self, languages):
        if not languages:
            return

        l = float(len(languages))
        weight = 0
        for index, language in enumerate(languages):
            if language.lower() in self.language.lower():
                weight += (l - index) / l

        self.weight += weight

    def match_release(self, release):
        self.weight += len(release & self.release_hash) / 2.

    def match_completeness(self, completeness):
        match = re.match('(\d+\.?\d+)', self.completeness)
        weight = float(match.group(1)) / 100 if match else 1
        self.weight += weight

    def __unicode__(self):
        return u'{language} - {release} {infos} {completeness}' \
            .format(**self.__dict__)

    def __str__(self):
        return unicode(self).encode('utf-8')

    def download(self, filename):
        with open(filename, 'wb') as fp:
            fp.write(get(self.url, raw=True))


class UI(object):

    def __init__(self, args, filename):
        self.args = args
        self.filename = filename

    def select(self, choices):
        if not choices:
            raise Exception("no choices!")

        if len(choices) == 1 or self.args.batch:
            result = 1

        else:
            just = len(str(len(choices)))
            index = 1
            for choice in choices:
                print str(index).rjust(just), ':', choice
                index += 1

            while True:
                try:
                    result = int(raw_input('> '))
                except ValueError:
                    result = None
                except KeyboardInterrupt as e:
                    print e
                    exit(1)
                if not result or not 1 <= result <= len(choices):
                    print "bad response"
                else:
                    break

        result = choices[result - 1]
        print result
        return result

    def search(self, query):
        results = Episode.search(query)

        if not results:
            print 'No results'

        else:
            return self.select(results)

    def episode(self, episode, user_languages=[], user_releases=[]):
        episode.fetch_versions()
        versions = episode.filter_versions(user_languages, user_releases, True)
        return self.select(versions)

    def confirm(self, question):
        question += ' [yn]> '

        if self.args.batch:
            return True

        while True:
            answer = raw_input(question)
            if answer in 'yn':
                break

            else:
                print 'Bad answer'

        return answer == 'y'

    def launch(self):
        print '-' * 30
        args = self.args
        filename = self.filename

        if os.path.isfile(filename) and not filename.endswith('.srt'):
            filename = remove_extension(filename) + '.srt'

        print 'Target SRT file:', filename
        ignore = False
        if os.path.isfile(filename):
            print 'File exists.',
            if args.ignore or (not args.overwrite and
                               not self.confirm('Overwrite?')):
                print 'Ignoring.'
                ignore = True

            else:
                print 'Overwriting.'

        if not ignore:
            query, release = file_to_query(filename)

            if args.query:
                query = args.query

            if args.release:
                release = string_set(' '.join(args.release))

            todownload = self.episode(self.search(query), args.language,
                                      release)
            todownload.download(filename)

        print


def file_to_query(filename):
    basename = os.path.basename(filename).lower()
    basename = remove_extension(basename)
    basename = normalize_whitespace(basename)
    # remove parenthesis
    basename = re.sub(r'[\[(].*[\])]', '', basename)
    basename = re.sub(r'\bdont\b', 'don\'t', basename)
    episode = re.search(r'\S*0+(\d+)[xe](\d+)', basename) or \
        re.search(r'(\d+)', basename)

    if episode:
        index = basename.find(episode.group(0))
        release = basename[index + len(episode.group(0)):]
        basename = basename[:index]
        episode = 'x'.join(episode.groups())

    else:
        episode = ''
        release = basename

    query = normalize_whitespace(' '.join((basename, episode)))
    release = string_set(release)
    return query, release


def remove_extension(filename):
    return filename.rpartition('.')[0] if '.' in filename else filename


def normalize_whitespace(string):
    # change extra characters to space
    return re.sub(r'[\s._,-]+', ' ', string).strip()


def string_set(string):
    string = normalize_whitespace(string.lower())
    return set(string.split(' ')) if string else set()


def main():

    import argparse
    parser = argparse.ArgumentParser(description='Downloads SRT files from '
                                     'addic7ed.com.')
    parser.add_argument('file', nargs='+',
                        help='Video file name')
    parser.add_argument('-q', '--query',
                        help='Query (default: based on the filename)')
    parser.add_argument('-r', '--release', action='append', default=[],
                        help='Release (default: based on the filename)')
    # parser.add_argument('-p', '--play', action='store_true',
    #         help='Play the video after loading subtitles')
    parser.add_argument('-o', '--overwrite', action='store_true',
                        help='Overwrite the original SRT file without asking')
    parser.add_argument('-i', '--ignore', action='store_true',
                        help='Ignore the original SRT file without asking')
    parser.add_argument('-l', '--language', action='append', default=[],
                        help='Auto select language (could be specified more '
                        'than one time for fallbacks)')
    parser.add_argument('-b', '--batch', action='store_true',
                        help='Batch mode: do not ask anything, get the best '
                        'matching subtitle')
    args = parser.parse_args()

    for file in args.file:
        UI(args, file).launch()


if __name__ == '__main__':
    main()
