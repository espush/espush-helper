#!/usr/bin/env python
# encoding: utf-8

import os
import threading
import serial

from PyQt4 import QtNetwork
from PyQt4.QtGui import QWidget, QApplication, QMessageBox, QMenu, QCursor
from PyQt4.QtNetwork import QNetworkRequest, QNetworkReply
from PyQt4.QtCore import Qt, QVariant, QUrl, QObject, QThread, pyqtSignal, QByteArray, QFile, QIODevice, QSize
from PyQt4 import QtGui, QtCore


SERIAL_READ_TIMEOUT = 0.5


class SerialContext(QObject):
    open_serial_sig = pyqtSignal(dict)
    close_serial_sig = pyqtSignal()
    write_data_sig = pyqtSignal(str)
    # running on main ui thread
    data_received_sig = pyqtSignal(int)
    serial_opened_sig = pyqtSignal()
    serial_closed_sig = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        # self.open_serial_sig.connect(self.open_serial)
        # self.write_data_sig.connect(self.write_data)
        self._serial = None
        self._exit = False

    def close_serial(self):
        assert self._serial != None
        self._serial.close()
        if not self._serial.is_open:
            self.serial_closed_sig.emit()
        self._serial = None
        self._exit = True

    def write_data(self, cmd):
        print('write_data running on %d' % threading.currentThread().ident)
        assert self._serial != None
        self._serial.write(cmd)

    def open_serial(self, obj):
        print('open_serial running on %d' % threading.currentThread().ident)
        assert 'baud' in obj
        assert 'port' in obj
        assert 'bytesize' in obj
        assert 'parity' in obj
        assert 'stopbits' in obj
        assert self._serial is None
        bytesizes = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS
        }
        parity = {
            'None': serial.PARITY_NONE,
            'Even': serial.PARITY_EVEN,
            'Odd': serial.PARITY_ODD,
            'Mark': serial.PARITY_MARK,
            'Space': serial.PARITY_SPACE,
        }
        stopbits = {
            '1': serial.STOPBITS_ONE,
            '1.5': serial.STOPBITS_ONE_POINT_FIVE,
            '2': serial.STOPBITS_TWO
        }
        self._serial = serial.Serial()
        self._serial.port = obj['port']
        self._serial.baudrate = obj['baud']
        self._serial.bytesize = bytesizes[obj['bytesize']]
        self._serial.parity = parity[obj['parity']]
        self._serial.stopbits = stopbits[obj['stopbits']]
        self._serial.timeout = SERIAL_READ_TIMEOUT
        self._serial.open()
        print(self._serial.is_open)
        if self._serial.is_open:
            self.serial_opened_sig.emit()
            self.read_forever()

    def read_forever(self):
        while 1:
            QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents | QtCore.QEventLoop.ExcludeSocketNotifiers)
            print("reading...")
            if self._exit == True:
                print('exit serial context thread.')
                break
            word = self._serial.read()
            if word:
                print('w:[%d]' % ord(word))
                self.data_received_sig.emit(ord(word))
            else:
                print("no data recved.")

