class MessageColors:

    def __init__(self):
        self.header = '\033[95m'
        self.blue = '\033[94m'
        self.green = '\033[92m'
        self.warning = '\033[93m'
        self.deepblue = '\033[1;34m'
        self.red = '\033[1;31m'
        self.fail = '\033[91m'
        self.endc = '\033[0m'
        self.white = '\033[1;37m'

    def disable(self):
        self.header = ''
        self.blue = ''
        self.green = ''
        self.warning = ''
        self.fail = ''
        self.endc = ''

    def normalmessage(self, mesaj):
        return self.white+mesaj+self.disable

    def headermessage(self,mesaj):
        return self.header+mesaj+self.disable

    def failuremessage(self,mesaj):
        return self.fail+mesaj+self.disable

    def __del__(self):
        self.disable()
