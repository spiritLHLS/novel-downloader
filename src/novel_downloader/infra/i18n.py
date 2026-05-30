#!/usr/bin/env python3
"""
novel_downloader.infra.i18n
---------------------------

"""

__all__ = ["t"]

import gettext
from importlib.resources import files

from novel_downloader.infra.persistence.state import state_mgr


def get_translation(lang: str) -> gettext.NullTranslations:
    try:
        locales = files("novel_downloader.locales")
        try:
            mo_path = locales.joinpath(lang, "LC_MESSAGES", "messages.mo")
        except TypeError:
            mo_path = (
                locales.joinpath(lang)
                .joinpath("LC_MESSAGES")
                .joinpath("messages.mo")
            )
        with mo_path.open("rb") as f:
            return gettext.GNUTranslations(f)
    except (FileNotFoundError, ModuleNotFoundError):
        return gettext.NullTranslations()


_lang = state_mgr.get_language()
_translation = get_translation(_lang)

t = _translation.gettext
