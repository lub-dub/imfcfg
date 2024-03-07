# IMFCFG

This is mostly still a work in progress, and lots of cleanup is still
required but its in a shape that most of the hardcoded c3noc specific
features are abstracted away so it can be made public.

== install ==

install with `pip install .` inside a venv

== setup ==

Change the relevant values in c3site.py
populate .netboxrc with the relevant values

== to run ==

run `flask updater` in the background and `flask --app imfcfg.frontend run` for the webui


== local run ==

run `python -m imfcfg.c3cfg <arguments` for a local exection`

