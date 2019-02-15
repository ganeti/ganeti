{-# LANGUAGE OverloadedStrings #-}
{-| /proc/stat file parser

This module holds the definition of the parser that extracts information
about the CPU load of the system from the @/proc/stat@ file.

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
module Ganeti.Cpu.LoadParser (cpustatParser) where

import Control.Applicative ((<*>), (<*), (*>), (<$>), (<|>))
import qualified Data.Attoparsec.Text as A
import qualified Data.Attoparsec.Combinator as AC
import Data.Attoparsec.Text (Parser)

import Ganeti.Parsers
import Ganeti.Cpu.Types

-- * Parser implementation

-- | The parser for one line of the CPU status file.
oneCPUstatParser :: Parser CPUstat
oneCPUstatParser =
  let nameP = stringP
      userP = numberP
      niceP = numberP
      systemP = numberP
      idleP = numberP
      iowaitP = numberP
      irqP = numberP
      softirqP = numberP
      stealP = numberP
      guestP = numberP
      guest_niceP = numberP
  in
    CPUstat <$> nameP <*> userP <*> niceP <*> systemP <*> idleP <*> iowaitP
            <*> irqP <*> softirqP <*> stealP <*> guestP <*> guest_niceP
            <* A.endOfLine

-- | When this is satisfied all the lines containing information about
-- the CPU load are parsed.
intrFound :: Parser ()
intrFound = (A.string "intr" *> return ())
             <|> (A.string "page" *> return ())
             <|> (A.string "swap" *> return ())

-- | The parser for the fragment of CPU status file containing
-- information about the CPU load.
cpustatParser :: Parser [CPUstat]
cpustatParser = oneCPUstatParser `AC.manyTill` intrFound
