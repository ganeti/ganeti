{-| Main htools binary.

-}

{-

Copyright (C) 2011, 2012 Google Inc.

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

import Control.Exception
import Control.Monad (guard)
import Data.Char (toLower)
import Prelude hiding (catch)
import System.Environment
import System.Exit
import System.IO
import System.IO.Error (isDoesNotExistError)

import Ganeti.Utils
import Ganeti.HTools.CLI (parseOpts, genericOpts)
import Ganeti.HTools.Program (personalities)

-- | Display usage and exit.
usage :: String -> IO ()
usage name = do
  hPutStrLn stderr $ "Unrecognised personality '" ++ name ++ "'."
  hPutStrLn stderr "This program must be installed under one of the following\
                   \ names:"
  mapM_ (hPutStrLn stderr . ("  - " ++) . fst) personalities
  hPutStrLn stderr "Please either rename/symlink the program or set\n\
                   \the environment variable HTOOLS to the desired role."
  exitWith $ ExitFailure 1

main :: IO ()
main = do
  binary <- catchJust (guard . isDoesNotExistError)
            (getEnv "HTOOLS") (const getProgName)
  let name = map toLower binary
      boolnames = map (\(x, y) -> (x == name, Just y)) personalities
  case select Nothing boolnames of
    Nothing -> usage name
    Just (fn, options) -> do
         cmd_args <- getArgs
         (opts, args) <- parseOpts cmd_args name $ options ++ genericOpts
         fn opts args
