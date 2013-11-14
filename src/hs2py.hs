{-| Haskell to Python opcode generation program.

-}

{-

Copyright (C) 2011, 2012, 2013 Google Inc.

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

import Ganeti.Hs2Py.GenOpCodes
import Ganeti.Hs2Py.ListConstants

import System.Environment (getArgs)
import System.Exit (exitFailure)
import System.IO (hPutStrLn, stderr)

main :: IO ()
main = do
  args <- getArgs
  case args of
    ["--opcodes"] -> putStrLn showPyClasses
    ["--constants"] -> putConstants
    _ -> do
      hPutStrLn stderr "Usage: hs2py --opcodes | --constants"
      exitFailure
