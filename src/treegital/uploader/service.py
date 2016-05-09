# -*- coding: utf-8 -*-

import ConfigParser
import cgi
import datetime
import hashlib
import codecs
import logging
import os
import re
import shutil
import uuid
import json

from os.path import join
from stat import ST_SIZE, ST_CTIME
from .ticket import UUID_ATM

try:
    # py3
    from tempfile import TemporaryDirectory
except ImportError:
    from ._compat import TemporaryDirectory


RETRY = 10
CHUNKSIZE = 4096
INNER_ENCODING = 'utf-8'

logger = logging.getLogger('verification')
logger.setLevel(logging.INFO)


_filename_ascii_strip_re = re.compile(r'[^A-Za-z0-9_.-]')
_windows_device_files = (
    'CON', 'AUX', 'COM1', 'COM2', 'COM3',
    'COM4', 'LPT1', 'LPT2', 'LPT3', 'PRN', 'NUL')


def chunk_reader(fobj, chunk_size=CHUNKSIZE):
    """Generator that reads a file in chunks of bytes
    """
    while True:
        chunk = fobj.read(chunk_size)
        if not chunk:
            return
        yield chunk


def digest(fobj, hash=hashlib.sha1):
    hashobj = hash()
    size = os.fstat(fobj.fileno()).st_size
    hashobj.update("blob %i\0" % size)
    for chunk in chunk_reader(fobj):
        hashobj.update(chunk)
    fobj.seek(0)
    return hashobj.hexdigest()


def clean_filename(filename):
    """Borrowed from Werkzeug : http://werkzeug.pocoo.org/
    """
    for sep in os.path.sep, os.path.altsep:
        if sep:
            filename = filename.replace(sep, ' ')

    filename = filename.strip()

    # on nt a couple of special files are present in each folder. We
    # have to ensure that the target file is not such a filename. In
    # this case we prepend an underline
    if os.name == 'nt' and filename and \
       filename.split('.')[0].upper() in _windows_device_files:
        filename = '_' + filename

    if not isinstance(filename, unicode):
        filename = unicode(filename, INNER_ENCODING).encode(INNER_ENCODING)
    return filename


class ConfigParserManifest(object):

    def __init__(self, dest, name="MANIFEST"):
        self.dest = dest
        self.manifest = join(dest, name)

    def write(self, *files, **extra):
        config = ConfigParser.RawConfigParser()
        config.add_section('DEFAULT')
        for key, value in extra.items():
            config.set('DEFAULT', key, value)

        for digest, filename in files:
            path = join(self.dest, digest)
            stats = os.stat(path)
            config.add_section(digest)
            
            config.set(digest, 'name', filename)
            config.set(digest, 'size', stats[ST_SIZE])
            config.set(digest, 'date', stats[ST_CTIME])

        with codecs.open(self.manifest, 'wb+') as fd:
            config.write(fd)

    def read(self):
        data = {}
        config = ConfigParser.ConfigParser()
        with codecs.open(self.manifest, 'r', encoding='utf-8') as fd:
            config.readfp(fd)

        for section in config.sections():
            data[section] = dict(config.items(section))
            
        return data


class JSONManifest(object):

    def __init__(self, dest, name="MANIFEST"):
        self.dest = dest
        self.manifest = join(dest, name)

    def write(self, *files, **extra):
        config = {}
        config['DEFAULT'] = extra
        for digest, filename in files:
            path = join(self.dest, digest)
            stats = os.stat(path)
            config[digest] = {            
                'name': filename,
                'size': stats[ST_SIZE],
                'date': stats[ST_CTIME],
                }
            
        with open(self.manifest, 'wb+') as fd:
            json.dump(config, fd, indent=4)

    def read(self):
        with open(self.manifest, 'r') as fd:
            data = json.load(fd)
        return data

    
def create_file(path, name):
    filepath = join(path, name)
    try:
        if not os.path.exists(filepath):
            return filepath
    except OSError, e:
        logger.error(e)
    return None


def create_directory(path):
    try:
        if not os.path.exists(path):
            os.makedirs(path)
        return path
    except OSError, e:
        return None


def persist_files(destination, *files):
    """Document me.
    """
    # digest registry
    digests = set()

    for item in files:
        digested = digest(item.file)
        if digested not in digests:
            digests.add(digested)
            filename = clean_filename(item.filename)
            path = join(destination, digested)
            with open(path, 'w') as upload:
                shutil.copyfileobj(item.file, upload)
            yield (digested, filename)


def extract_files(environ):
    fields = cgi.FieldStorage(
        fp=environ['wsgi.input'], environ=environ, keep_blank_values=1)    

    for name in fields.keys():
        field = fields[name]
        if not isinstance(field, list):
            # handle multiple fields of same name (html5 uploads)
            field = [field]

        for item in field:
            if isinstance(item, cgi.FieldStorage) and item.filename:
                yield item


def extract_and_persist(environ, destination):
    extracted = list(extract_files(environ))
    return persist_files(destination, *extracted)


class FilesystemHandler(object):
    """Document me.
    """
    ignore = set(('MANIFEST',))

    def __init__(self, upload, namespace):
        self.__upload = upload
        self.namespace = namespace

    @property
    def upload_root(self):
        return join(self.__upload, self.namespace)

    def ticket_files(self, ticket):
        path = self.atm.get_path(ticket)
        for listed in os.listdir(path):
            if listed not in self.ignore:
                yield listed

    def upload(self, upload_node, files):
        with TemporaryDirectory() as tmpdirname:
            uploaded = list(persist_files(tmpdirname, *files))
            destination = join(self.upload_root, upload_node)
            shutil.copytree(tmpdirname, destination)
            return destination, uploaded

    def extract_upload(self, upload_node, environ):
        """The heart of the handler.
        """
        with TemporaryDirectory() as tmpdirname:
            uploaded = list(extract_and_persist(environ, tmpdirname))
            destination = join(self.upload_root, upload_node)
            shutil.copytree(tmpdirname, destination)
            return destination, uploaded


class Uploader(object):
    """the uploading application
    """
    def __init__(self, upload_root, namespace, atm=UUID_ATM):
        self.atm = atm
        self.fs_handler = FilesystemHandler(upload_root, namespace)
        self.mf_handler = ConfigParserManifest

    def __call__(self, environ, start_response):
        ticket = self.atm.generate()
        path = self.atm.get_path(ticket)
        dest, files = self.fs_handler.extract_upload(path, environ)
        manifest = self.mf_handler(dest)
        manifest.write(*files)
        status = '200 OK'
        response_headers = [('Content-type','application/json')]
        start_response(status, response_headers)
        return [json.dumps(manifest.read(), indent=4, sort_keys=True)]


def upload_service(*global_conf, **local_conf):
    namespace = local_conf.get('namespace')
    upload = local_conf.get('upload')

    return Uploader(upload, namespace)
