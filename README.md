# Electrons Inventory System #

### What is this repository for? ###

This is the inventory system initially written to manage the electronic components used by the electronics subgroup in the [University of Auckland Formula SAE Team](https://www.fsae.co.nz/). It allows the user to scan DigiKey bags to add components into the system, as well as to search and edit the information.

### Current state of the project ###

Currently, the system has working basic features and the rest is still a work in progress. The features include:

* Adding components by scanning DigiKey datamatrix code

* Adding components by manual entry

* Searching for a part by any keyword (basic search) or by fields (advanced search). Results are currently limited to 200

* Edit component information by code scanning or search


Future features that I would like to implement include:

* Packaged executable for Windows

* Multi-page search results display with no limits

* Automatic component deduction by project bill of materials

* Automatic scheduled database backup

There are also room for improvements in the usability of the GUI.

### Required hardware ###

* USB webcam for scanning codes, one that can adjust the focus (either manually or auto-focus) is strongly recommended.

The system was developed using a 640x480 USB webcam with an adjustable lens. Cameras with different resolutions should work, although higher resolution cameras might be harder to scan, as the datamatrix code detection algorithm might time out more easily having more data to process.

### How do I get it set up? ###

At the moment, the system will be run directly using python. This means that some external libraries the project depends on need to be installed via pip. There has been progress in packaging the app into a stand-alone executable, but it's not ready yet.

The required libraries list can be found in the requirements.txt file.
