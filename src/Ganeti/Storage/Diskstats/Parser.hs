{-# LANGUAGE OverloadedStrings #-}
{-| Diskstats proc file parser

This module holds the definition of the parser that extracts status
information about the disks of the system from the @/proc/diskstats@ file.

-}
{-

Copyright (C) 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}
module Ganeti.Storage.Diskstats.Parser (diskstatsParser) where

import Control.Applicative ((<*>), (<*), (<$>))
import qualified Data.Attoparsec.Text as A
import qualified Data.Attoparsec.Combinator as AC
import Data.Attoparsec.Text (Parser)

import Ganeti.Parsers
import Ganeti.Storage.Diskstats.Types

-- * Parser implementation

-- | The parser for one line of the diskstatus file.
oneDiskstatsParser :: Parser Diskstats
oneDiskstatsParser =
  let majorP = numberP
      minorP = numberP
      nameP = stringP
      readsNumP = numberP
      mergedReadsP = numberP
      secReadP = numberP
      timeReadP = numberP
      writesP = numberP
      mergedWritesP = numberP
      secWrittenP = numberP
      timeWriteP = numberP
      iosP = numberP
      timeIOP = numberP
      wIOmillisP = numberP
  in
    Diskstats <$> majorP <*> minorP <*> nameP <*> readsNumP <*> mergedReadsP
      <*> secReadP <*> timeReadP <*> writesP <*> mergedWritesP <*> secWrittenP
      <*> timeWriteP <*> iosP <*> timeIOP <*> wIOmillisP <* A.endOfLine

-- | The parser for a whole diskstatus file.
diskstatsParser :: Parser [Diskstats]
diskstatsParser = oneDiskstatsParser `AC.manyTill` A.endOfInput
