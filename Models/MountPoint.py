#!/usr/bin/env python

import pyinotify
import os

class MountPoint:

    def __init__(self, options_dict):
        """
        """
        self.mounted = False
        self.options_dict = options_dict

    def activate_sync(self, *lista):
        """
        takes a list of directories to activate synchronization
        it can also be used to add more watch descriptors if for example
        we couldn't/didn't add them when the instance was created
        can also be used to add more ProcessEvent instances rather
        than GenericEventHandler
        ( i.e. we can differentiate different actions and different
          handlers between google & dropbox )
        proc_fun=None
        """
        if lista:
            self.mounted = True
            print("-> watching: %s" % lista)
        else:
            pass

        from Models.EventHandlers import GenericEventHandler, GoogleEventHandler
        self.wm = pyinotify.WatchManager() # Watch Manager
        self.mask = pyinotify.IN_MODIFY | pyinotify.IN_DELETE | pyinotify.IN_CREATE # watched events
       
        ## wdd = watch descriptors
        self.wdd = []
        self.wdd.append(self.wm.add_watch(os.path.abspath(lista[0]), self.mask, rec=True, auto_add=True))
        # we need to pass the watch descripors ( self.wdd ) to GoogleEventHandler() as well
        # because we need them to split the pathnames
        self.notifier = pyinotify.AsyncNotifier(self.wm, GoogleEventHandler(self.options_dict, self.wdd))

        if self.mounted and len(self.wdd) > 0:
            print("-> mounted: %s" % self.wdd)

    def deactivate_sync(self, *lista):
        """
        takes a list of directories to deactivate
        watch descriptors
        """
        for i in lista:
            if self.wdd[i] > 0:
                self.wm.rm_watch(lista)
                print("-> deactivated: " % i)
            else:
                print("%s not activated! " % i)
        # remove google / dropbox stuff here if necessary

    def daemonize(self):
        try:
            self.notifier.loop(stdout=self.options_dict['LOGFILE'])
        except pyinotify.WatchManagerError as err:
            print("%s" % err)