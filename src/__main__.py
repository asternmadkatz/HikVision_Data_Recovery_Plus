"""
HIKVISION Video Data Recovery
Author: Dane Wullen
Date: 2024
Version: 0.2
NO WARRANTY, SOFWARE IS PROVIDED 'AS IS'


© 2024 Dane Wullen
"""

import argparse
import os
import shutil
from src.hikparser import HikParser
from src.unindex_recovery import UnindexRecovery

def main():

    print("########################################")
    print("HIKVISION Video Data Recovery")
    print("Version 0.2")
    print("© 2024 Dane Wullen")
    print("NO WARRANTY, SOFWARE IS PROVIDED 'AS IS'")
    print("########################################")

    ap = argparse.ArgumentParser()

    ap.add_argument("-m", "--mode", required=True, help="Information (i) or extraction (e)")
    ap.add_argument("-i", "--input", required=True, help="Inputfile (.dd or .001)")
    ap.add_argument("-d", "--dir", required=True, help="Output-Directory for logs and/or videos")
    ap.add_argument("--unindex", action="store_true", help="Enable UNINDEX extraction mode")
    ap.add_argument(
        "--unindex-mode",
        choices=["block", "carve", "hybrid"],
        default="hybrid",
        help="UNINDEX strategy (default: hybrid)")
    ap.add_argument(
        "--unindex-max",
        type=int,
        default=0,
        help="Maximum UNINDEX files to create per run (0 = unlimited)")
    ap.add_argument(
        "--carve-window",
        type=int,
        default=512,
        help="Deep carve scan window size in MB from video area start (default: 512)")
    args = vars(ap.parse_args())

    print("Read file: {}".format(args.get("input")))

    parser = HikParser(r'%s' % args.get("input"))
    parser.read_master_sector()
    parser.read_hikbtree()
    parser.read_page_list()
    parser.read_page_entries()
    parser.print_hikpagelist(args.get("dir"))
    parser.print_hikpages(args.get("dir"))
    parser.print_master_sector(args.get("dir"))
    parser.print_hikbtree(args.get("dir"))

    if args.get("mode") == "e":

        required_space = parser.get_total_blocks() * parser.master_sector.data_block_size
        total, used, free = shutil.disk_usage(args.get("dir"))

        required_space = int(required_space) / pow(1024, 3)
        free = int(free) / pow(1024, 3)

        if required_space >= int(free):
            print(
                "Insufficient hard disk space! Required: %d gb, available %d gb" % (required_space, free))
            return

        if not os.path.isdir(args.get("dir")):
            os.makedirs(args.get("dir"))

        parser.extract_block(args.get("dir"))

        if args.get("unindex"):
            recovery = UnindexRecovery(
                parser=parser,
                export_dir=args.get("dir"),
                mode=args.get("unindex_mode"),
                unindex_max=args.get("unindex_max"),
                carve_window_mb=args.get("carve_window")
            )
            recovery.run()

    print("Done! Bye bye!")

if __name__ == "__main__":
    main()