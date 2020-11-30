#!/usr/bin/python3
import datetime
import http.client
import json
from mailer import Mailer
from twilio.rest import Client
from urllib.parse import urlparse

# Test product:
#PRODUCT_LINK = 'https://www.chainreactioncycles.com/us/en/lifeline-essential-torque-wrench-set/rp-prod155414'
PRODUCT_LINK = 'https://www.chainreactioncycles.com/us/en/lifeline-pro-mechanic-wheel-truing-stand/rp-prod122322'

def loadSettings(settingsFileName):
    with open(settingsFileName, 'r') as f:
        settings = f.read()
    return json.loads(settings)

class Logger:
    def __init__(self, settings):
        self._settings = settings
        self._log = ''
        self._finalMessage = ''
        self._inStock = None

    def reportStep(self, stepMessage):
        print(stepMessage)
        self._log += stepMessage + '\n'

    def reportError(self, errorMessage):
        print(errorMessage)
        self._log += errorMessage + '\n'
    
    def logDetail(self, detail):
        print(detail)
        self._log += detail + '\n'

    def logFinalMessage(self, message, inStock):
        # Don't log more than once
        assert self._finalMessage == ''
        print(message)
        self._log += message + '\n'
        self._finalMessage = message
        self._inStock = inStock

    def _emailReport(self):
        self.logDetail('Emailing report')
        try:
            mailer = Mailer('mail_settings.json', 'Web Page Checker', self._settings['from_address'])
            if self._finalMessage == '' or self._inStock is None:
                mailer.send_mail(self._settings['to_address'], 'Failures Checking Product Stock', 'Failed to check product stock for truing stand\n\nLog:\n' + self._log)
            else:
                if self._inStock:
                    mailer.send_mail(self._settings['to_address'], 'Truing Stand Is In Stock!', 'The truing stand is in Stock! Order it now!\n{0}\n\nLog:\n{1}'.format(PRODUCT_LINK, self._log))
                else:
                    mailer.send_mail(self._settings['to_address'], 'Truing Stand Is Still Not In Stock', 'We will keep checking.\n\nLog:\n' + self._log)
        except Exception as e:
            self.logDetail('Exception "{0}" sending report email'.format(e))
            self.reportError('Failed to send report email')

    def _textReport(self):
        self.logDetail('Texting report')
        try:
            if self._finalMessage == '' or self._inStock is None:
                message = 'Failures checking Product Stock. Log file was sent via email'
            else:
                if self._inStock:
                    # Only send a text if the product is in stock
                    message = 'The truing stand is in Stock! Order it now! {0}'.format(PRODUCT_LINK)
                else:
                    self.logDetail('Not sending text: check was successful, but the product is not in stock')
                    return
            self.logDetail('Sending text')
            client = Client(self._settings['twilio_sid'], self._settings['twilio_auth_token'])
            message = client.messages.create(to=self._settings['to_number'], from_=self._settings['from_number'], body=message)
        except Exception as e:
            self.logDetail('Exception "{0}" sending report text'.format(e))
            self.reportError('Failed to send report text')

    def sendReport(self):
        self.logDetail('Sending report')
        self._textReport()
        self._emailReport()
        with open('check.log', 'a') as logFile:
            logFile.write('{0}\n{1}'.format(datetime.datetime.now(), self._log))

class Checker:
    def __init__(self, settings, logger):
        self._settings = settings
        self._logger = logger

    def downloadWebPage(self, url):
        try:
            urlParts = urlparse(url)
            connection = http.client.HTTPSConnection(urlParts.hostname)
            connection.request('GET', urlParts.path)
            response = connection.getresponse()
            if response.code != 200:
                self._logger.logDetail('Got response {0} from HTTP request'.format(response.code))
            return response.read().decode('utf-8')
        except Exception as e:
            self._logger.logDetail('Exception {0} downloading web page'.format(e))
        return None

    def parseVariable(self, pageContent, variableName):
        def sumBraces(currentBraceCount, line):
            for c in line:
                if c == '{':
                    currentBraceCount += 1
                elif c == '}':
                    currentBraceCount -= 1
            return currentBraceCount
        openBraceCount = 0
        variable = ''
        for line in pageContent.split('\n'):
            if openBraceCount == 0 and variableName in line:
                if not '=' in line or not '{' in line:
                    self._logger.logDetail('Line has variable name, but no = or open brace: {0}'.format(line))
                    continue
                openBraceCount = sumBraces(openBraceCount, line)
                variable += line + '\n'
            elif openBraceCount > 0:
                variable += line + '\n'
                openBraceCount = sumBraces(openBraceCount, line)
            elif openBraceCount == 0 and len(variable) > 0:
                break
        variable = variable.strip()
        variable = variable.replace('"', '{{double_quote_temp_value}}')
        variable = variable.replace('\'', '"')
        variable = variable.replace('{{double_quote_temp_value}}', '"')
        jsonData = variable[variable.find('{'):]
        try:
            return json.loads(jsonData)
        except Exception as e:
            self._logger.logDetail('Exception "{0}" parsing variable {1} from page content'.format(e, variableName))
        return None

    def fetchFromDict(self, dictionary, key):
        if not key in dictionary:
            self._logger.logDetail('Key "{0}" not found in dictionary'.format(key))
            return None
        return dictionary[key]

    def checkStock(self, pageData):
        def parseBoolFromValue(value):
            if value.upper() == 'TRUE':
                return True
            if value.upper() == 'FALSE':
                return False
            return None

        productData = self.fetchFromDict(pageData, 'product')
        if productData is None:
            return False
        inStock = self.fetchFromDict(productData, 'in_stock')
        if inStock is None:
            return False
        inStock = parseBoolFromValue(inStock)
        if inStock is None:
            return False

        self._logger.logFinalMessage('Product is{0} in stock'.format('' if inStock else ' not'), inStock)
        return True

    def checkItemInventory(self):
        self._logger.reportStep('Downloading web page content...')
        
        pageContent = self.downloadWebPage(PRODUCT_LINK)
        if pageContent is None:
            self._logger.reportError('Failed to download web page')
            return

        self._logger.reportStep('Parsing web page...')
        universal_variable = self.parseVariable(pageContent, 'window.universal_variable')
        if universal_variable is None:
            self._logger.reportError('Failed to parse "universal_variable" from page data')
            return
        
        self._logger.reportStep('Checking stock...')
        if not self.checkStock(universal_variable):
            self._logger.reportError('Failed to check stock variable')
            return

if __name__ == "__main__":
    settings = loadSettings('settings.json')
    logger = Logger(settings)
    checker = Checker(settings, logger)
    checker.checkItemInventory()
    logger.sendReport()