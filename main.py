#!/usr/bin/env/python

import sys
import os
import argparse
import textwrap
import logging
import time
import signal
import mimetypes

from Models.MountPoint import MountPoint
from Models.ServiceProviders.Google import GoogleServiceProvider
from daemon import runner

parser = argparse.ArgumentParser(prog="SyncThemAll", usage="python main.py --realtime <list of mountpoints> --initialize <optional: google_client_id google_client_secret> ",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description=textwrap.dedent('''\
        SyncThemAll
        -----------
        A  Linux command line Google Drive Client
        Written in Python, released under GPL
        Uses pyinotify to get events from the filesystem: https://github.com/seb-m/pyinotify

        --start:
                    Should NOT be used on very busy filesystems!
                    Specify a list of absolute paths, like this:
                    python main.py --realtime /var /home /root

        --initialize:
                    Should be run only once, when setting the application up.
                    If successful, it will create a file called "credstore.json" in the folder where the main.py program resides.
                    python main.py --initialize 1077359083816-49381jdfmbfqj4m1sb2ub8tmdt7ddu6n.apps.googleusercontent.com H4GgY3jXg1GhQ3BQ1WMBJU8-

        --download:
                    Downloads the contents of a Google Drive folder to the local filesystem
                    Should be called like this:
                    python main.py --download <local folder name (abspath)> <gdrive folder name>
                    python main.py --download /tmp/temp SyncThemAll

        --upload:
                Uploads the contents of a local folder to Google Drive:
                python main.py --upload /var/temp SyncThemAll



        '''))


parser.add_argument('--version', action='version', version='%(prog)s 1.0')
parser.add_argument('--initialize', nargs=2, required=False,
    help="Should be called only once, to generate the refresh token for Google API.\n")
parser.add_argument('--download', nargs=2, required=False,
    help="Will download the GDrive directory into a local folder.\n")
parser.add_argument('--upload', nargs=2, required=False,
    help="Will upload the local folder/file to the GDrive folder specified.\n")
parser.add_argument('--stop', action='store_true')
parser.add_argument('--start', nargs='*', help="A space separated list containing the directories which should be monitored.\n")
args = parser.parse_args()

dict = {}
dict['watched_dirs'] = args.start
dict['initialize'] = args.initialize
dict['download'] = args.download
dict['upload'] = args.upload
jsonfile = os.path.realpath(__file__).split(os.path.basename(__file__))[0]+'Config/credstore.json' # the credentials file for OAuth2
treefile = os.path.realpath(__file__).split(os.path.basename(__file__))[0]+'Config/filebase.json' # the tree hierarchy of local fs / google id
logfile = os.path.realpath(__file__).split(os.path.basename(__file__))[0]+'Logs/all.log'

if not os.path.isfile(jsonfile) and not dict['initialize']:
    print("No credstore found, run python main.py --initialize first!")
    sys.exit(1)

options_dict = {}
options_dict['jsonfile'] = jsonfile
# this is basically the permissions list for the Google Account:
options_dict['OAUTH_SCOPES'] = ['https://www.googleapis.com/auth/drive',
                                'https://www.googleapis.com/auth/drive.file']
                                # 11'https://www.googleapis.com/auth/userinfo.email']
                                # 'https://www.googleapis.com/auth/userinfo.profile',]
options_dict['REDIRECT_URI'] = 'urn:ietf:wg:oauth:2.0:oob'
options_dict['DEFAULT_PARENT'] = 'root'
options_dict['treefile'] = treefile
options_dict['LOGFILE'] = logfile
options_dict['FILE_SYNC_INTERVAL'] = 5 # seconds

file_list = [];
folder_list = [];

# make a global debug logging object
x = logging.getLogger("mainlog")
x.setLevel(logging.DEBUG)
f = logging.Formatter("%(levelname)s %(funcName)s %(lineno)d %(message)s")
h1 = logging.FileHandler(options_dict['LOGFILE'])
h1.setFormatter(f)
h1.setLevel(logging.DEBUG)
x.addHandler(h1)

class Main():
    def __init__(self, args, options_dict):
        self.args=args
        self.options_dict=options_dict

        self.stdin_path = '/dev/null'
        self.stdout_path = options_dict['LOGFILE']
        self.stderr_path = options_dict['LOGFILE']
        self.pidfile_path =  '/tmp/SyncThemAll.pid'
        self.pidfile_timeout = 5

    def download(self):
        if args.download is not None:
            options_dict['download'] = dict['download']
            sp = GoogleServiceProvider(**options_dict)
            ds = sp.build_service(sp.get_stored_credentials('testid'))
            ds = ds[1]
            parent_id = sp.query_entity(ds, "title = '"+options_dict['download'][1]+"'")[0] #[1] = gdrive source folder
            target_dir = options_dict['download'][0]
            print("Found: %s" % parent_id)
            def create_list(download_list):
                print("ITEMS IN DOWNLOAD_LIST %s:" % len(download_list))
                if len(download_list) > 0:
                    for entity in reversed(download_list):
                        print(type(entity))
                        if entity['mimeType'] == 'application/vnd.google-apps.folder':
                            global folder_list
                            folder_list.append(download_list.pop())
                            for item in sp.query_entity(ds,"'"+entity['id']+"'"+" in parents"):
                                print("appending: %s" % item)
                                download_list.append(item)
                                create_list(download_list)
                        else:
                            global file_list
                            file_list.append(entity)
                            print("Files in FILE_LIST: %s " % file_list)
                            continue
                    print("Found: %s files" % len(file_list))
                else:
                    return 0

            download_list = sp.query_entity(ds, "'"+parent_id['id']+"'"+" in parents")

            create_list(download_list)
            print("Found: %s files." % len(file_list))
            print("Found: %s folders." % len(folder_list))
            for file in file_list:
                print("Original Filename: %s" % file['originalFilename'])
            for folder in folder_list:
                print("Folder object: %s" % folder)
            sp.download_files(ds, folder_list, target_dir)
            sp.download_files(ds, file_list, target_dir)
            sys.exit(0)

    def upload(self):
        if args.upload is not None:
            sp = GoogleServiceProvider(**options_dict)
            ds = sp.build_service(sp.get_stored_credentials('testid'))
            ds = ds[1]
            def evproc(filename,parent, parent_id=None):
                # obtain full path
                fullpath = os.path.join(filename, parent)
                fullpath = os.path.join(fullpath, filename)
                t = (filename, fullpath, parent)
                if os.path.isfile(filename):
                    t = (filename, parent)
                    print("Uploading: %s" % (t,))

                    ## the path relative to event.pathname will end up on the description tab in google drive
                    ## this is so we can download the file and preserve the relative directory structure
                    #create the body of the file here:
                    if parent_id is None:
                        parent_id = sp.query_entity(ds,"title = '"+parent+"'")[0] # always returns the first folder with that name found

                    # get mimetype:
                    mimeType = mimetypes.guess_type(filename)[0] or 'text/plain'
                    body = {
                            'title': os.path.basename(filename),
                            'description': fullpath.replace(filename+"/", "", 1),
                            'mimeType': mimeType,
                            'parents': [
                                        {
                                        "kind": "drive#parentReference",
                                        "id": parent_id['id'],
                                        }
                                    ],
                            }
                    if os.path.getsize(fullpath) > 0:
                        sp.upload_file(filename,fullpath,ds, body)
                    else:
                        print("File %s is empty" % fullpath)

                if os.path.isdir(filename):
                    if parent_id is None:
                        parent_id = sp.query_entity(ds,"title = '"+parent+"'")[0] # always returns the first folder with that name found
                    folder_name = os.path.basename(os.path.abspath(filename))
                    t = (filename, filename.replace(filename,"",1))
                    body = {
                    'title': folder_name,
                    'description': filename.replace(filename+"/","",1),
                    'mimeType':  'application/vnd.google-apps.folder',
                    "parents": [
                        {
                            "kind": "drive#parentReference",
                            "id": parent_id['id'],
                        }
                    ],
                    }
                    directory = sp.create_folder(ds,body)
                    if directory:
                        parent_id = directory # this is exactly what query_entity(), called by
                        old_parent = parent      # create_folder() returns
                        new_parent = folder_name
                        t = (old_parent, new_parent)
                        print("old, new parent is: %s" % (t,) )
                        for (fullpath, dirs, files) in os.walk(filename):
                            for f in reversed(files):
                                evproc(os.path.join(fullpath, files.pop()), new_parent, parent_id)
                            for d in reversed(dirs):
                                evproc(os.path.join(fullpath, dirs.pop()), new_parent, parent_id)
                    else:
                        print("couldnt create: %s" % directory)
            evproc(dict['upload'][0],dict['upload'][1])
            sys.exit(0)

    def initialize(self):
        if args.initialize is not None:
            options_dict['CLIENT_ID'] = dict['initialize'][0]
            options_dict['CLIENT_SECRET'] = dict['initialize'][1]
            sp = GoogleServiceProvider(**options_dict)
            if isinstance(sp, GoogleServiceProvider):
                # user is prompted to access the authorization url here
                sp.get_refresh_token()
                try:
                    with open(jsonfile) as f:
                        print("Refresh token written to: %s" % jsonfile)
                        f.close()
                        sys.exit(1)
                except Exception, e:
                    print("%s" % e)
                    sys.exit(1)
    def run(self):
        mtpt = MountPoint(options_dict)
        for d in dict['watched_dirs']:
            mtpt.activate_sync(d)
        mtpt.daemonize()

    def stop(self):
        try:
            while True:
                with open(self.pidfile_path, 'r') as infile:
                    self.pid=infile.readline()
                os.kill(int(self.pid), signal.SIGTERM)
                time.sleep(0.1)
        except (OSError, IOError) as err:
            err = str(err)

        if err.find("No such process") > 0:
            if os.path.exists(self.pidfile_path):
                os.remove(self.pidfile_path)
            else:
                sys.stdout.write(str(err))
                sys.exit(1)

if __name__ == '__main__':
    app = Main(args,options_dict)
    if args.start:
        sys.argv[1] = 'start'
        daemon_runner = runner.DaemonRunner(app)
        daemon_runner.do_action()
    if args.stop:
        sys.argv[1] = 'stop'
        app.stop()
    if args.initialize:
        app.initialize()
    if args.upload:
        app.upload()
    if args.download:
        app.download()
