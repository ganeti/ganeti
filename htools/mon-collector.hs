{-| Main binary for all stand-alone data collectors

-}

{-

Copyright (C) 2012 Google Inc.

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

module Main (main) where

import Data.Char (toLower)
import System.Environment
import System.IO

import Ganeti.Utils
import Ganeti.HTools.CLI (parseOpts, genericOpts)
import Ganeti.DataCollectors.Program (personalities)

-- | Display usage and exit.
usage :: String -> IO ()
usage name = do
  hPutStrLn stderr $ "Unrecognised personality '" ++ name ++ "'."
  hPutStrLn stderr "This program must be executed specifying one of the \
                    \following names as the first parameter:"
  mapM_ (hPutStrLn stderr . ("  - " ++) . fst) personalities
  exitErr "Please specify the desired role."

main :: IO ()
main = do
  cmd_args <- getArgs
  let binary =
        if null cmd_args
          then ""
          else head cmd_args
      name = map toLower binary
      boolnames = map (\(x, y) -> (x == name, Just y)) personalities
  case select Nothing boolnames of
    Nothing -> usage name
    Just (fn, options, arguments) -> do
         let actual_args = tail cmd_args
         real_options <- options
         (opts, args) <- parseOpts actual_args name (real_options ++
                           genericOpts) arguments
         fn opts args
