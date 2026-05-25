devhacks
========

A collection of utility scripts for homelab media management, Docker inspection, and file operations.

Scripts
-------

Python (``devhacks/``)
~~~~~~~~~~~~~~~~~~~~~~

+------------------------------+----------------------------------------------------------------+
| Script                       | Description                                                    |
+==============================+================================================================+
| ``compare_media_flow.py``    | Scans ingest dirs (torrents/usenet) vs media libraries.        |
|                              | Reports counts, sizes, % organized, backlog of unprocessed.    |
+------------------------------+----------------------------------------------------------------+
| ``list_docker_ports.py``     | Lists all exposed/mapped ports for running Docker containers.  |
+------------------------------+----------------------------------------------------------------+
| ``remove_every_other_file.py`` | Removes every other file (even-indexed) from a directory.    |
+------------------------------+----------------------------------------------------------------+

Shell (``scripts/``)
~~~~~~~~~~~~~~~~~~~~

+------------------------------+----------------------------------------------------------------+
| Script                       | Description                                                    |
+==============================+================================================================+
| ``downscale_to_720p.sh``     | Batch downscale videos to 720p using ffmpeg (VAAPI GPU accel   |
|                              | if available, CPU fallback).                                   |
+------------------------------+----------------------------------------------------------------+
| ``jf_delete_unmonitor.sh``   | Unmonitor and delete a title from Sonarr/Radarr/Whisparr.      |
+------------------------------+----------------------------------------------------------------+
| ``summary_table.sh``         | Show name, size, and file count for subdirectories. Sortable   |
|                              | by name, size, or file count.                                  |
+------------------------------+----------------------------------------------------------------+

Requirements
------------

- Python 3.7+ (``poetry install`` for Python scripts)
- ``docker`` Python package (for ``list_docker_ports.py``)
- ``ffmpeg``/``ffprobe`` (for ``downscale_to_720p.sh``)
- ``curl``/``jq`` (for ``jf_delete_unmonitor.sh``)

Usage
-----

.. code-block:: bash

    # Compare media ingest vs libraries
    python devhacks/compare_media_flow.py --ingest /path/to/completed --libraries /path/to/media

    # List Docker container ports
    python devhacks/list_docker_ports.py

    # Remove every other file in a directory
    python devhacks/remove_every_other_file.py /path/to/dir

    # Downscale videos to 720p
    ./scripts/downscale_to_720p.sh /path/to/videos

    # Unmonitor + delete a title from *arr
    ./scripts/jf_delete_unmonitor.sh "Show Name"

    # Directory summary table
    ./scripts/summary_table.sh /path/to/dir
    ./scripts/summary_table.sh -S /path/to/dir   # sort by size
