#!/usr/bin/env python
# encoding: utf-8


import os
import sys
import time
import serial
import struct
import hashlib
import requests
from serial.tools.list_ports import comports


from PyQt4 import QtNetwork
from PyQt4.QtGui import QWidget, QApplication, QMessageBox, QMenu, QCursor
from PyQt4.QtNetwork import QNetworkRequest, QNetworkReply
from PyQt4.QtCore import QVariant, QUrl, QObject, QThread, pyqtSignal, QByteArray, QFile, QIODevice


from etool import ESPROM, div_roundup


FLASH_BAUD = 576000


class ESP8266Flasher(QObject):
    begin_flash_sig = pyqtSignal(str, dict)
    abort_flash_sig = pyqtSignal()
    conn_result_sig = pyqtSignal(int)
    flash_progress_sig = pyqtSignal(int, int)
    flash_result_sig = pyqtSignal(int, str)
    console_sig = pyqtSignal(str)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        self._is_abort = False

    def sync_dev(self):
        try:
            self.consolelog(u'串口同步中，请勿终止')
            self.esp8266.connect()
            return True
        except Exception as e:
            print(e)
            return False

    def consolelog(self, s):
        self.console_sig.emit(s)

    def _flash_write(self, comport, firmwares):
        sync_result = self.sync_dev()
        QApplication.processEvents()
        print('IS_ABORT: %d %d' % (self._is_abort, sync_result))
        self.conn_result_sig.emit(0 if sync_result else 1)
        # 同步设备失败
        if not sync_result:
            self.esp8266.close()
            return
        # 检查是否要终止烧录
        if self._is_abort:
            self.flash_result_sig.emit(1, u'已终止')
            self.esp8266.close()
            return
        flash_info = self.make_flash_info()
        total_size = len(firmwares['boot']) + len(firmwares['app1']) + 3 * len(firmwares['blank']) + len(firmwares['init'])
        self.flash_write(flash_info, 0, firmwares['boot'], total_size)
        self.flash_write(flash_info, 0x1000, firmwares['app1'], total_size)
        self.flash_write(flash_info, 0xc8000, firmwares['blank'], total_size)
        self.flash_write(flash_info, 0x3fb000, firmwares['blank'], total_size)
        self.flash_write(flash_info, 0x3fc000, firmwares['init'], total_size)
        self.flash_write(flash_info, 0x3fe000, firmwares['blank'], total_size)
        self.flash_result_sig.emit(0, u'成功')

    def begin_flash(self, comport, firmwares):
        self._is_abort = False
        port = str(comport.toUtf8())
        try:
            self.esp8266 = ESPROM(port, FLASH_BAUD)
        except serial.serialutil.SerialException as _:
            self.consolelog(u'串口读写失败，请检查是否有其他程序占用了指定串口')
            self.flash_result_sig.emit(1, u'串口读写失败')
            return
        self._flash_write(comport, firmwares)
        self.esp8266.close()

    def make_flash_info(self):
        flash_mode = {'qio': 0, 'qout': 1, 'dio': 2, 'dout': 3}['dio']
        flash_size_freq = {'4m': 0x00, '2m': 0x10, '8m': 0x20, '16m': 0x30, '32m': 0x40, '16m-c1': 0x50, '32m-c1': 0x60, '32m-c2': 0x70}['32m-c1']
        flash_size_freq += {'40m': 0, '26m': 1, '20m': 2, '80m': 0xf}['40m']
        return struct.pack('BB', flash_mode, flash_size_freq)

    def flash_write(self, flash_info, address, content, total_size):
        image = str(content)
        print('write flash %d' % len(image))
        self.consolelog(u'Flash擦除工作进行中，请保持设备连接。')
        blocks = div_roundup(len(content), self.esp8266.ESP_FLASH_BLOCK)
        self.esp8266.flash_begin(blocks * self.esp8266.ESP_FLASH_BLOCK, address)
        seq = 0
        written = 0
        t = time.time()
        while len(image) > 0:
            QApplication.processEvents()
            if self._is_abort:
                self.flash_result_sig.emit(1, u'已终止')
                self.esp8266.close()
                return
            # print('\rWriting at 0x%08x... (%d %%)' % (address + seq * self.esp8266.ESP_FLASH_BLOCK, 100 * (seq + 1) / blocks),)
            sys.stdout.flush()
            block = image[0: self.esp8266.ESP_FLASH_BLOCK]
            actual_written = len(block)
            # Fix sflash config data
            if address == 0 and seq == 0 and block[0] == b'\xe9':
                block = block[0:2] + flash_info + block[4:]
            # Pad the last block
            block = block + b'\xff' * (self.esp8266.ESP_FLASH_BLOCK - len(block))
            self.esp8266.flash_block(block, seq)
            image = image[self.esp8266.ESP_FLASH_BLOCK:]
            seq += 1
            written += len(block)
            self.flash_progress_sig.emit(actual_written, total_size)
        t = time.time() - t
        print('\rWrote %d bytes at 0x%08x in %.1f seconds (%.1f kbit/s)...' % (written, address, t, written / t * 8 / 1000))

    def abort_flash(self):
        print('abort flash.')
        self._is_abort = True

