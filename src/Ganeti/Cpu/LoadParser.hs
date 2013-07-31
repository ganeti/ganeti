{-# LANGUAGE OverloadedStrings #-}
{-| /proc/stat file parser

This module holds the definition of the parser that extracts information
about the CPU load of the system from the @/proc/stat@ file.

-}
{-

Copyright (C) 2013 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

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
