"""
HIKVISION Video Data Recovery
Author: Dane Wullen
Date: 2024
Version: 0.2
NO WARRANTY, SOFWARE IS PROVIDED 'AS IS'


© 2024 Dane Wullen
"""

import uuid
import os

from .hikpageentry import HikPageEntry
from .hikbtree import HikBTree
from .hikmastersector import HikMasterSector
from .hikdatablockentry import HikDataBlockEntry
from .diskimage import DiskImage

import datetime
import hashlib

class HikParser(Exception):

    def set_pos(self, pos):
        self.diskimage.seek(pos)

    def skip_bytes(self, offset):
        self.diskimage.skip(offset)

    def __init__(self, filename):
        self.diskimage = DiskImage(filename)
        self.master_sector = HikMasterSector()
        self.hikbtree = HikBTree()
        self.hikbtree.page_list = []

    def get_total_blocks(self):
        total = 0
        for page in self.hikbtree.get_page_list():
            total += len(page.data_blocks)

        return total

    def hex_to_string(self, hex):
        return bytes.fromhex(str(hex)[2:])

    def from_byte_to_string(self, bytestring):
        return bytestring.decode("utf-8")

    def from_byte_to_int(self, bytestring, byteorder):
        return int.from_bytes(bytestring, byteorder=byteorder)

    def hex_to_ascii(self, hex):
        return bytes.fromhex(str(hex)[2:]).decode("windows-1252").strip(' \t\n\r')

    def _get_export_subdir(self, base_dir, start_time):
        date_obj = datetime.datetime.utcfromtimestamp(start_time)
        month_dir = date_obj.strftime("%Y-%m")
        day_dir = date_obj.strftime("%Y-%m-%d")
        target_dir = os.path.join(base_dir, month_dir, day_dir)
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir, exist_ok=True)
        return target_dir

    def _build_block_basename(self, datablock):
        start_txt = datetime.datetime.utcfromtimestamp(datablock.start_time).strftime('%Y-%m-%d_%H-%M-%S')
        end_txt = datetime.datetime.utcfromtimestamp(datablock.end_time).strftime('%Y-%m-%d_%H-%M-%S')
        return "{}-{}_ch_{}_off_{}".format(
            start_txt,
            end_txt,
            datablock.channel,
            datablock.data_offset
        )

    def _resolve_unique_path(self, full_path):
        if not os.path.exists(full_path):
            return full_path
        base, ext = os.path.splitext(full_path)
        return "{}_id_{}{}".format(base, uuid.uuid4(), ext)

    def _has_legacy_pair(self, target_dir, start_txt, end_txt, channel):
        prefix = "{}-{}_ch_{}_".format(start_txt, end_txt, channel)
        try:
            for name in os.listdir(target_dir):
                if not name.endswith(".mp4"):
                    continue
                if not name.startswith(prefix):
                    continue
                paired_md5 = os.path.splitext(name)[0] + ".md5"
                if os.path.isfile(os.path.join(target_dir, paired_md5)):
                    return True
        except OSError:
            return False
        return False

    def read_master_sector(self):
        """
           Reads master sector of HIKVISION systems and write its content into class.
           Initial position should always be Offset 528 Byte.
        """

        self.set_pos(528)
        self.master_sector.signatur = self.from_byte_to_string(self.diskimage.read(32))

        if not self.master_sector.check_signatur():
            raise Exception('SignatureException: Signature not equal to HIKVISION@HANGZHOU!')

        self.skip_bytes(24)
        self.master_sector.hdd_cap = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.skip_bytes(16)
        self.master_sector.sys_log_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.master_sector.sys_log_size = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.skip_bytes(8)
        self.master_sector.video_data_area_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.skip_bytes(8)
        self.master_sector.data_block_size = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.master_sector.data_block_total = self.from_byte_to_int(self.diskimage.read(4), "little")
        self.skip_bytes(4)
        self.master_sector.hikbtree1_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.master_sector.hikbtree1_size = self.from_byte_to_int(self.diskimage.read(4), "little")
        self.skip_bytes(4)
        self.master_sector.hikbtree2_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.master_sector.hikbtree2_size = self.from_byte_to_int(self.diskimage.read(4), "little")
        self.skip_bytes(60)
        # UTC Timestamp
        self.master_sector.init_time = datetime.datetime.fromtimestamp(self.from_byte_to_int(self.diskimage.read(4),
                                                                                             "little"))\
            .strftime('%d.%m.%Y %H:%M:%S')

    def read_hikbtree(self):
        """
            Reads the first of the two HISBTREES and writes to class.
            Initial offset for HIBKTREE is located in master sector.
        """

        self.set_pos(self.master_sector.hikbtree1_offset)
        # Skip 16 unused bytes
        self.skip_bytes(16)
        self.hikbtree.signatur = self.from_byte_to_string(self.diskimage.read(8))
        self.skip_bytes(36)
        self.hikbtree.created_time = datetime.datetime.fromtimestamp(self.from_byte_to_int(self.diskimage.read(4),
                                                                                           "little"))\
            .strftime('%d.%m.%Y %H:%M:%S'),
        self.hikbtree.footer_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.skip_bytes(8)
        self.hikbtree.page_list_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.hikbtree.page_one_offset = self.from_byte_to_int(self.diskimage.read(8), "little")

    def read_page_list(self):
        """ Reads page list page for page and writes content into list."""

        self.set_pos(self.hikbtree.page_list_offset)
        self.skip_bytes(24)
        first_page_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
        self.skip_bytes(64)
        # self.skip_bytes(96)
        page_offset = self.from_byte_to_int(self.diskimage.read(8), "little")

        # Add first page to entries
        page = HikPageEntry()
        page.offset_to_page = first_page_offset
        page.data_blocks = []
        self.hikbtree.add_hikpage(page)

        while page_offset != 0:
            page = HikPageEntry()
            page.offset_to_page = page_offset
            self.skip_bytes(8)
            page.channel = self.from_byte_to_int(self.diskimage.read(2), "big")
            self.skip_bytes(6)
            page.start_time = self.from_byte_to_int(self.diskimage.read(4), "little")
            page.end_time = self.from_byte_to_int(self.diskimage.read(4), "little")
            page.data_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
            page.data_blocks = []
            self.hikbtree.add_hikpage(page)
            self.skip_bytes(8)
            page_offset = self.from_byte_to_int(self.diskimage.read(8), "little")

    def read_page_entries(self):
        def _valid_epoch(ts):
            # Accept roughly 2010-01-01 .. 2035-01-01 UTC.
            return 1262304000 <= ts <= 2051222400

        def _is_plausible_entry(channel, start_time, end_time, data_offset):
            return (
                1 <= channel <= 64 and
                _valid_epoch(start_time) and
                _valid_epoch(end_time) and
                start_time <= end_time and
                0 < data_offset < self.master_sector.hdd_cap
            )

        for page in self.hikbtree.get_page_list():
            base_offset = page.offset_to_page
            start_rel = None

            # HikVision variants may store first entry at +96, +104 or +112.
            for candidate_rel in [96, 104, 112]:
                self.set_pos(base_offset + candidate_rel)
                self.diskimage.read(8)  # existence marker (varies by firmware)
                channel = self.from_byte_to_int(self.diskimage.read(2), "big")
                self.skip_bytes(6)
                start_time = self.from_byte_to_int(self.diskimage.read(4), "little")
                end_time = self.from_byte_to_int(self.diskimage.read(4), "little")
                data_offset = self.from_byte_to_int(self.diskimage.read(8), "little")

                if _is_plausible_entry(channel, start_time, end_time, data_offset):
                    start_rel = candidate_rel
                    break

            if start_rel is None:
                continue

            # Records are fixed-size pages of 40 bytes in known variants.
            record_size = 40
            max_records_per_page = 131072
            max_consecutive_invalid = 256
            consecutive_invalid = 0

            for index in range(max_records_per_page):
                self.set_pos(base_offset + start_rel + index * record_size)
                data_block = HikDataBlockEntry()
                data_block.existence_of_file = self.diskimage.read(8)
                data_block.channel = self.from_byte_to_int(self.diskimage.read(2), "big")
                self.skip_bytes(6)
                data_block.start_time = self.from_byte_to_int(self.diskimage.read(4), "little")
                data_block.end_time = self.from_byte_to_int(self.diskimage.read(4), "little")
                data_block.data_offset = self.from_byte_to_int(self.diskimage.read(8), "little")
                self.skip_bytes(8)

                if _is_plausible_entry(
                        data_block.channel,
                        data_block.start_time,
                        data_block.end_time,
                        data_block.data_offset):
                    page.data_blocks.append(data_block)
                    consecutive_invalid = 0
                    continue

                consecutive_invalid += 1
                if consecutive_invalid >= max_consecutive_invalid:
                    break

    def extract_block(self, dir):
        i = 1
        for page in self.hikbtree.get_page_list():
            j = 1
            for datablock in page.data_blocks:
                length = self.master_sector.data_block_size
                target_dir = self._get_export_subdir(dir, datablock.start_time)
                start_txt = datetime.datetime.utcfromtimestamp(datablock.start_time).strftime('%Y-%m-%d_%H-%M-%S')
                end_txt = datetime.datetime.utcfromtimestamp(datablock.end_time).strftime('%Y-%m-%d_%H-%M-%S')
                file_basename = self._build_block_basename(datablock)
                fileName = os.path.join(target_dir, file_basename + ".mp4")
                fileNameMD5 = os.path.join(target_dir, file_basename + ".md5")

                if (os.path.isfile(fileName) and os.path.isfile(fileNameMD5)) or \
                        self._has_legacy_pair(target_dir, start_txt, end_txt, datablock.channel):
                    print("Block {} of page {} already extracted. Skipping.".format(j, i))
                    j += 1
                    continue

                # Collision fallback keeps deterministic naming unless needed.
                fileName = self._resolve_unique_path(fileName)
                fileNameMD5 = os.path.splitext(fileName)[0] + ".md5"

                md5Hash = hashlib.md5()
                self.diskimage.seek(datablock.data_offset)
                with open(fileName, 'wb') as f2:
                    while length:
                        chunk = min(1024 * 1024, length)
                        data = self.diskimage.read(chunk)
                        f2.write(data)
                        length -= chunk
                        md5Hash.update(data)
                    print("Block {} of page {} extracted!".format(j, i))
                with open (fileNameMD5, 'w') as f3:
                    f3.write(md5Hash.hexdigest())
                f2.close()
                f3.close()
                j += 1
                #f1.close()
            i += 1

    def print_hikpagelist(self, dir):
        with open(dir + "\\HIKPageList.csv", "w", newline="") as file:
            i = 1
            file.write("Page;Channel;Starttime;Endtime;Offset\n")
            for page in self.hikbtree.get_page_list():
                output = "{};{};{};{};{}".format(
                    str(i),
                    page.channel,
                    datetime.datetime.utcfromtimestamp(page.start_time).strftime('%d.%m.%Y %H:%M:%S'),
                    datetime.datetime.utcfromtimestamp(page.end_time).strftime('%d.%m.%Y %H:%M:%S'),
                    page.offset_to_page
                )
                file.write(output + "\n")
                i += 1
        file.close()

    def print_hikbtree(self, dir):
        with open(dir + "\\HIKBTree.txt", "w", newline="") as file:
            file.write("Signature: {}\n".format(self.hikbtree.signatur))
            file.write("Creation date: {}\n".format(self.hikbtree.created_time))
            file.write("Offset to footer: {}\n".format(self.hikbtree.footer_offset))
            file.write("Offset to page list: {}\n".format(self.hikbtree.page_list_offset))
            file.write("Offset to first page: {}\n".format(self.hikbtree.page_one_offset))
        file.close()

    def print_hikpages(self, dir):
        with open(dir + "\\HIKPages.csv", "w", newline="") as file:
            i = 1
            file.write("Page;Datablock;Channel;Starttime;Endtime;Offset\n")
            for page_entry in self.hikbtree.get_page_list():
                j = 1
                for page in page_entry.data_blocks:
                    output = "{};{};{};{};{};{}".format(
                        str(i),
                        str(j),
                        int.from_bytes(self.hex_to_string(page.channel), byteorder="big"),
                        datetime.datetime.utcfromtimestamp(page.start_time).strftime('%d.%m.%Y %H:%M:%S'),
                        datetime.datetime.utcfromtimestamp(page.end_time).strftime('%d.%m.%Y %H:%M:%S'),
                        page.data_offset
                    )
                    file.write(output + "\n")
                    j += 1
                j = 0
                i += 1
        file.close()

    def print_master_sector(self, dir):
        with open(dir + "\\HIKMasterSector.txt", "w", newline="") as file:
            file.write("Signature: {}\n".format(self.master_sector.signatur))
            file.write("Hard disk size: {}\n".format(self.master_sector.hdd_cap))
            file.write("Offset to system logs: {}\n".format(self.master_sector.sys_log_offset))
            file.write("System log size: {}\n".format(self.master_sector.sys_log_size))
            file.write("Offset to video data area: {}\n".format(self.master_sector.video_data_area_offset))
            file.write("data block size: {}\n".format(self.master_sector.data_block_size))
            file.write("Total data blocks: {}\n".format(self.master_sector.data_block_total))
            file.write("Offset to HIKBTree 1: {}\n".format(self.master_sector.hikbtree1_offset))
            file.write("Size of HIKBTree 1: {}\n".format(self.master_sector.hikbtree1_size))
            file.write("Offset to HIKBTree 2: {}\n".format(self.master_sector.hikbtree2_offset))
            file.write("Size of HIKBTree 2: {}\n".format(self.master_sector.hikbtree2_size))
            file.write("Creation date: {}\n".format(self.master_sector.init_time))
        file.close()





