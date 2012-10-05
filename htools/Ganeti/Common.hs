{-| Base common functionality.

This module holds common functionality shared across Ganeti daemons,
HTools and any other programs.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

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

module Ganeti.Common
  ( GenericOptType
  , StandardOptions(..)
  , OptCompletion(..)
  , ArgCompletion(..)
  , optComplYesNo
  , oShowHelp
  , oShowVer
  , oShowComp
  , usageHelp
  , versionInfo
  , reqWithConversion
  , parseYesNo
  , parseOpts
  , parseOptsInner
  ) where

import Control.Monad (foldM)
import Data.Char (toLower)
import Data.List (intercalate, stripPrefix)
import Data.Maybe (fromMaybe)
import qualified Data.Version
import System.Console.GetOpt
import System.Exit
import System.Info
import System.IO
import Text.Printf (printf)

import Ganeti.BasicTypes
import qualified Ganeti.Version as Version (version)

-- | Parameter type.
data OptCompletion = OptComplNone             -- ^ No parameter to this option
                   | OptComplFile             -- ^ An existing file
                   | OptComplDir              -- ^ An existing directory
                   | OptComplHost             -- ^ Host name
                   | OptComplInetAddr         -- ^ One ipv4\/ipv6 address
                   | OptComplOneNode          -- ^ One node
                   | OptComplManyNodes        -- ^ Many nodes, comma-sep
                   | OptComplOneInstance      -- ^ One instance
                   | OptComplManyInstances    -- ^ Many instances, comma-sep
                   | OptComplOneOs            -- ^ One OS name
                   | OptComplOneIallocator    -- ^ One iallocator
                   | OptComplInstAddNodes     -- ^ Either one or two nodes
                   | OptComplOneGroup         -- ^ One group
                   | OptComplInteger          -- ^ Integer values
                   | OptComplFloat            -- ^ Float values
                   | OptComplJobId            -- ^ Job Id
                   | OptComplCommand          -- ^ Command (executable)
                   | OptComplString           -- ^ Arbitrary string
                   | OptComplChoices [String] -- ^ List of string choices
                   | OptComplSuggest [String] -- ^ Suggested choices
                   deriving (Show, Read, Eq)

-- | Argument type. This differs from (and wraps) an Option by the
-- fact that it can (and usually does) support multiple repetitions of
-- the same argument, via a min and max limit.
data ArgCompletion = ArgCompletion OptCompletion Int (Maybe Int)
                     deriving (Show, Read, Eq)

-- | Yes\/no choices completion.
optComplYesNo :: OptCompletion
optComplYesNo = OptComplChoices ["yes", "no"]

-- | Text serialisation for 'OptCompletion', used on the Python side.
complToText :: OptCompletion -> String
complToText (OptComplChoices choices) = "choices=" ++ intercalate "," choices
complToText (OptComplSuggest choices) = "suggest=" ++ intercalate "," choices
complToText compl =
  let show_compl = show compl
      stripped = stripPrefix "OptCompl" show_compl
  in map toLower $ fromMaybe show_compl stripped

-- | Tex serialisation for 'ArgCompletion'.
argComplToText :: ArgCompletion -> String
argComplToText (ArgCompletion optc min_cnt max_cnt) =
  complToText optc ++ " " ++ show min_cnt ++ " " ++ maybe "none" show max_cnt

-- | Abrreviation for the option type.
type GenericOptType a = (OptDescr (a -> Result a), OptCompletion)

-- | Type class for options which support help and version.
class StandardOptions a where
  helpRequested :: a -> Bool
  verRequested  :: a -> Bool
  compRequested :: a -> Bool
  requestHelp   :: a -> a
  requestVer    :: a -> a
  requestComp   :: a -> a

-- | Option to request help output.
oShowHelp :: (StandardOptions a) => GenericOptType a
oShowHelp = (Option "h" ["help"] (NoArg (Ok . requestHelp)) "show help",
             OptComplNone)

-- | Option to request version information.
oShowVer :: (StandardOptions a) => GenericOptType a
oShowVer = (Option "V" ["version"] (NoArg (Ok . requestVer))
            "show the version of the program",
            OptComplNone)

-- | Option to request completion information
oShowComp :: (StandardOptions a) => GenericOptType a
oShowComp =
  (Option "" ["help-completion"] (NoArg (Ok . requestComp) )
   "show completion info", OptComplNone)

-- | Usage info.
usageHelp :: String -> [GenericOptType a] -> String
usageHelp progname =
  usageInfo (printf "%s %s\nUsage: %s [OPTION...]"
             progname Version.version progname) . map fst

-- | Show the program version info.
versionInfo :: String -> String
versionInfo progname =
  printf "%s %s\ncompiled with %s %s\nrunning on %s %s\n"
         progname Version.version compilerName
         (Data.Version.showVersion compilerVersion)
         os arch

-- | Show completion info.
completionInfo :: String -> [GenericOptType a] -> [ArgCompletion] -> String
completionInfo _ opts args =
  unlines $
  map (\(Option shorts longs _ _, compinfo) ->
         let all_opts = map (\c -> ['-', c]) shorts ++ map ("--" ++) longs
         in intercalate "," all_opts ++ " " ++ complToText compinfo
      ) opts ++
  map argComplToText args

-- | Helper for parsing a yes\/no command line flag.
parseYesNo :: Bool         -- ^ Default value (when we get a @Nothing@)
           -> Maybe String -- ^ Parameter value
           -> Result Bool  -- ^ Resulting boolean value
parseYesNo v Nothing      = return v
parseYesNo _ (Just "yes") = return True
parseYesNo _ (Just "no")  = return False
parseYesNo _ (Just s)     = fail ("Invalid choice '" ++ s ++
                                  "', pass one of 'yes' or 'no'")

-- | Helper function for required arguments which need to be converted
-- as opposed to stored just as string.
reqWithConversion :: (String -> Result a)
                  -> (a -> b -> Result b)
                  -> String
                  -> ArgDescr (b -> Result b)
reqWithConversion conversion_fn updater_fn =
  ReqArg (\string_opt opts -> do
            parsed_value <- conversion_fn string_opt
            updater_fn parsed_value opts)

-- | Command line parser, using a generic 'Options' structure.
parseOpts :: (StandardOptions a) =>
             a                      -- ^ The default options
          -> [String]               -- ^ The command line arguments
          -> String                 -- ^ The program name
          -> [GenericOptType a]     -- ^ The supported command line options
          -> [ArgCompletion]        -- ^ The supported command line arguments
          -> IO (a, [String])       -- ^ The resulting options and
                                    -- leftover arguments
parseOpts defaults argv progname options arguments =
  case parseOptsInner defaults argv progname options arguments of
    Left (code, msg) -> do
      hPutStr (if code == ExitSuccess then stdout else stderr) msg
      exitWith code
    Right result ->
      return result

-- | Inner parse options. The arguments are similar to 'parseOpts',
-- but it returns either a 'Left' composed of exit code and message,
-- or a 'Right' for the success case.
parseOptsInner :: (StandardOptions a) =>
                  a
               -> [String]
               -> String
               -> [GenericOptType a]
               -> [ArgCompletion]
               -> Either (ExitCode, String) (a, [String])
parseOptsInner defaults argv progname options arguments  =
  case getOpt Permute (map fst options) argv of
    (opts, args, []) ->
      case foldM (flip id) defaults opts of
           Bad msg -> Left (ExitFailure 1,
                            "Error while parsing command line arguments:\n"
                            ++ msg ++ "\n")
           Ok parsed ->
             select (Right (parsed, args))
                 [ (helpRequested parsed,
                    Left (ExitSuccess, usageHelp progname options))
                 , (verRequested parsed,
                    Left (ExitSuccess, versionInfo progname))
                 , (compRequested parsed,
                    Left (ExitSuccess, completionInfo progname options
                                         arguments))
                 ]
    (_, _, errs) ->
      Left (ExitFailure 2, "Command line error: "  ++ concat errs ++ "\n" ++
            usageHelp progname options)
