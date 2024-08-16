module Ganeti.Query.RegEx (
    RegEx.Regex,
    RegEx.match,
    RegEx.makeRegexM,
    (RegEx.=~),
    ) where

import qualified Text.Regex.PCRE as RegEx
