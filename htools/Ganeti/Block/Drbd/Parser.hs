{-# LANGUAGE OverloadedStrings #-}
{-| DRBD proc file parser

This module holds the definition of the parser that extracts status
information from the DRBD proc file.

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
module Ganeti.Block.Drbd.Parser (drbdStatusParser, commaIntParser) where

import Control.Applicative ((<*>), (*>), (<*), (<$>), (<|>), pure)
import qualified Data.Attoparsec.Text as A
import qualified Data.Attoparsec.Combinator as AC
import Data.Attoparsec.Text (Parser)
import Data.Text (Text, unpack)

import Ganeti.Block.Drbd.Types

-- | Our own space-skipping function, because A.skipSpace also skips
-- newline characters. It skips ZERO or more spaces, so it does not
-- fail if there are no spaces.
skipSpaces :: Parser ()
skipSpaces = A.skipWhile A.isHorizontalSpace

-- | Skips spaces and the given string, then executes a parser and
-- returns its result.
skipSpacesAndString :: Text -> Parser a -> Parser a
skipSpacesAndString s parser =
  skipSpaces
  *> A.string s
  *> parser

-- | Predicate verifying (potentially bad) end of lines
isBadEndOfLine :: Char -> Bool
isBadEndOfLine c = (c == '\0') || A.isEndOfLine c

-- | Takes a parser and returns it with the content wrapped in a Maybe
-- object. The resulting parser never fails, but contains Nothing if
-- it couldn't properly parse the string.
optional :: Parser a -> Parser (Maybe a)
optional parser = (Just <$> parser) <|> pure Nothing

-- | The parser for a whole DRBD status file.
drbdStatusParser :: Parser DRBDStatus
drbdStatusParser =
  DRBDStatus <$> versionInfoParser
             <*> deviceParser `AC.manyTill` A.endOfInput

-- | The parser for the version information lines.
versionInfoParser :: Parser VersionInfo
versionInfoParser =
  VersionInfo
    <$> optional versionP
    <*> optional apiP
    <*> optional protoP
    <*> optional srcVersion
    <*> (fmap unpack <$> optional gh)
    <*> (fmap unpack <$> optional builder)
    where versionP =
            A.string "version:"
            *> skipSpaces
            *> fmap unpack (A.takeWhile $ not . A.isHorizontalSpace)
          apiP =
            skipSpacesAndString "(api:" . fmap unpack $ A.takeWhile (/= '/')
          protoP =
            A.string "/proto:"
            *> fmap Data.Text.unpack (A.takeWhile (/= ')'))
            <* A.takeTill A.isEndOfLine <* A.endOfLine
          srcVersion =
            A.string "srcversion:"
            *> AC.skipMany1 A.space
            *> fmap unpack (A.takeTill A.isEndOfLine)
            <* A.endOfLine
          gh =
            A.string "GIT-hash:"
            *> skipSpaces
            *> A.takeWhile (not . A.isHorizontalSpace)
          builder =
            skipSpacesAndString "build by" $
              skipSpaces
              *> A.takeTill A.isEndOfLine
              <* A.endOfLine

-- | The parser for a (multi-line) string representing a device.
deviceParser :: Parser DeviceInfo
deviceParser = do
  deviceNum <- skipSpaces *> A.decimal <* A.char ':'
  cs <- skipSpacesAndString "cs:" connectionStateParser
  if cs == Unconfigured
    then do
      _ <- additionalEOL
      return $ UnconfiguredDevice deviceNum
    else do
      ro <- skipSpaces *> skipRoleString *> localRemoteParser roleParser
      ds <- skipSpacesAndString "ds:" $ localRemoteParser diskStateParser
      replicProtocol <- A.space *> A.anyChar
      io <- skipSpaces *> ioFlagsParser <* A.skipWhile isBadEndOfLine
      perfIndicators <- performanceIndicatorsParser
      syncS <- conditionalSyncStatusParser cs
      reS <- optional resyncParser
      act <- optional actLogParser
      _ <- additionalEOL
      return $ DeviceInfo deviceNum cs ro ds replicProtocol io perfIndicators
                          syncS reS act

    where conditionalSyncStatusParser SyncSource = Just <$> syncStatusParser
          conditionalSyncStatusParser SyncTarget = Just <$> syncStatusParser
          conditionalSyncStatusParser _ = pure Nothing
          skipRoleString = A.string "ro:" <|> A.string "st:"
          resyncParser = skipSpacesAndString "resync:" additionalInfoParser
          actLogParser = skipSpacesAndString "act_log:" additionalInfoParser
          additionalEOL = A.skipWhile A.isEndOfLine

-- | The parser for the connection state.
connectionStateParser :: Parser ConnectionState
connectionStateParser =
  standAlone
  <|> disconnecting
  <|> unconnected
  <|> timeout
  <|> brokenPipe
  <|> networkFailure
  <|> protocolError
  <|> tearDown
  <|> wfConnection
  <|> wfReportParams
  <|> connected
  <|> startingSyncS
  <|> startingSyncT
  <|> wfBitMapS
  <|> wfBitMapT
  <|> wfSyncUUID
  <|> syncSource
  <|> syncTarget
  <|> pausedSyncS
  <|> pausedSyncT
  <|> verifyS
  <|> verifyT
  <|> unconfigured
    where standAlone     = A.string "StandAlone"     *> pure StandAlone
          disconnecting  = A.string "Disconnectiog"  *> pure Disconnecting
          unconnected    = A.string "Unconnected"    *> pure Unconnected
          timeout        = A.string "Timeout"        *> pure Timeout
          brokenPipe     = A.string "BrokenPipe"     *> pure BrokenPipe
          networkFailure = A.string "NetworkFailure" *> pure NetworkFailure
          protocolError  = A.string "ProtocolError"  *> pure ProtocolError
          tearDown       = A.string "TearDown"       *> pure TearDown
          wfConnection   = A.string "WFConnection"   *> pure WFConnection
          wfReportParams = A.string "WFReportParams" *> pure WFReportParams
          connected      = A.string "Connected"      *> pure Connected
          startingSyncS  = A.string "StartingSyncS"  *> pure StartingSyncS
          startingSyncT  = A.string "StartingSyncT"  *> pure StartingSyncT
          wfBitMapS      = A.string "WFBitMapS"      *> pure WFBitMapS
          wfBitMapT      = A.string "WFBitMapT"      *> pure WFBitMapT
          wfSyncUUID     = A.string "WFSyncUUID"     *> pure WFSyncUUID
          syncSource     = A.string "SyncSource"     *> pure SyncSource
          syncTarget     = A.string "SyncTarget"     *> pure SyncTarget
          pausedSyncS    = A.string "PausedSyncS"    *> pure PausedSyncS
          pausedSyncT    = A.string "PausedSyncT"    *> pure PausedSyncT
          verifyS        = A.string "VerifyS"        *> pure VerifyS
          verifyT        = A.string "VerifyT"        *> pure VerifyT
          unconfigured   = A.string "Unconfigured"   *> pure Unconfigured

-- | Parser for recognizing strings describing two elements of the
-- same type separated by a '/'. The first one is considered local,
-- the second remote.
localRemoteParser :: Parser a -> Parser (LocalRemote a)
localRemoteParser parser = LocalRemote <$> parser <*> (A.char '/' *> parser)

-- | The parser for resource roles.
roleParser :: Parser Role
roleParser =
  primary
  <|> secondary
  <|> unknown
    where primary   = A.string "Primary"   *> pure Primary
          secondary = A.string "Secondary" *> pure Secondary
          unknown   = A.string "Unknown"   *> pure Unknown

-- | The parser for disk states.
diskStateParser :: Parser DiskState
diskStateParser =
  diskless
  <|> attaching
  <|> failed
  <|> negotiating
  <|> inconsistent
  <|> outdated
  <|> dUnknown
  <|> consistent
  <|> upToDate
    where diskless     = A.string "Diskless"     *> pure Diskless
          attaching    = A.string "Attaching"    *> pure Attaching
          failed       = A.string "Failed"       *> pure Failed
          negotiating  = A.string "Negotiating"  *> pure Negotiating
          inconsistent = A.string "Inconsistent" *> pure Inconsistent
          outdated     = A.string "Outdated"     *> pure Outdated
          dUnknown     = A.string "DUnknown"     *> pure DUnknown
          consistent   = A.string "Consistent"   *> pure Consistent
          upToDate     = A.string "UpToDate"     *> pure UpToDate

-- | The parser for I/O flags.
ioFlagsParser :: Parser String
ioFlagsParser = fmap unpack . A.takeWhile $ not . isBadEndOfLine

-- | The parser for performance indicators.
performanceIndicatorsParser :: Parser PerformanceIndicators
performanceIndicatorsParser =
  PerformanceIndicators
    <$> skipSpacesAndString "ns:" A.decimal
    <*> skipSpacesAndString "nr:" A.decimal
    <*> skipSpacesAndString "dw:" A.decimal
    <*> skipSpacesAndString "dr:" A.decimal
    <*> skipSpacesAndString "al:" A.decimal
    <*> skipSpacesAndString "bm:" A.decimal
    <*> skipSpacesAndString "lo:" A.decimal
    <*> skipSpacesAndString "pe:" A.decimal
    <*> skipSpacesAndString "ua:" A.decimal
    <*> skipSpacesAndString "ap:" A.decimal
    <*> optional (skipSpacesAndString "ep:" A.decimal)
    <*> optional (skipSpacesAndString "wo:" A.anyChar)
    <*> optional (skipSpacesAndString "oos:" A.decimal)
    <* skipSpaces <* A.endOfLine

-- | The parser for the syncronization status.
syncStatusParser :: Parser SyncStatus
syncStatusParser = do
  _ <- statusBarParser
  percent <-
    skipSpacesAndString "sync'ed:" $ skipSpaces *> A.double <* A.char '%'
  partSyncSize <- skipSpaces *> A.char '(' *> A.decimal
  totSyncSize <- A.char '/' *> A.decimal <* A.char ')'
  sizeUnit <- sizeUnitParser <* optional A.endOfLine
  timeToEnd <- skipSpacesAndString "finish:" $ skipSpaces *> timeParser
  sp <-
    skipSpacesAndString "speed:" $
      skipSpaces
      *> commaIntParser
      <* skipSpaces
      <* A.char '('
      <* commaIntParser
      <* A.char ')'
  w <- skipSpacesAndString "want:" (
         skipSpaces
         *> (Just <$> commaIntParser)
       )
       <|> pure Nothing
  sSizeUnit <- skipSpaces *> sizeUnitParser
  sTimeUnit <- A.char '/' *> timeUnitParser
  _ <- A.endOfLine
  return $
    SyncStatus percent partSyncSize totSyncSize sizeUnit timeToEnd sp w
      sSizeUnit sTimeUnit

-- | The parser for recognizing (and discarding) the sync status bar.
statusBarParser :: Parser ()
statusBarParser =
  skipSpaces
  *> A.char '['
  *> A.skipWhile (== '=')
  *> A.skipWhile (== '>')
  *> A.skipWhile (== '.')
  *> A.char ']'
  *> pure ()

-- | The parser for recognizing data size units (only the ones
-- actually found in DRBD files are implemented).
sizeUnitParser :: Parser SizeUnit
sizeUnitParser =
  kilobyte
  <|> megabyte
    where kilobyte = A.string "K" *> pure KiloByte
          megabyte = A.string "M" *> pure MegaByte

-- | The parser for recognizing time (hh:mm:ss).
timeParser :: Parser Time
timeParser = Time <$> h <*> m <*> s
  where h = A.decimal :: Parser Integer
        m = A.char ':' *> A.decimal :: Parser Integer
        s = A.char ':' *> A.decimal :: Parser Integer

-- | The parser for recognizing time units (only the ones actually
-- found in DRBD files are implemented).
timeUnitParser :: Parser TimeUnit
timeUnitParser = second
  where second = A.string "sec" *> pure Second

-- | Haskell does not recognise ',' as the thousands separator every 3
-- digits but DRBD uses it, so we need an ah-hoc parser.
-- If a number beginning with more than 3 digits without a comma is
-- parsed, only the first 3 digits are considered to be valid, the rest
-- is not consumed, and left for further parsing.
commaIntParser :: Parser Int
commaIntParser = do
  first <-
    AC.count 3 A.digit <|> AC.count 2 A.digit <|> AC.count 1 A.digit
  allDigits <- commaIntHelper (read first)
  pure allDigits

-- | Helper (triplet parser) for the commaIntParser
commaIntHelper :: Int -> Parser Int
commaIntHelper acc = nextTriplet <|> end
  where nextTriplet = do
          _ <- A.char ','
          triplet <- AC.count 3 A.digit
          commaIntHelper $ acc * 1000 + (read triplet :: Int)
        end = pure acc :: Parser Int

-- | Parser for the additional information provided by DRBD <= 8.0.
additionalInfoParser::Parser AdditionalInfo
additionalInfoParser = AdditionalInfo
  <$> skipSpacesAndString "used:" A.decimal
  <*> (A.char '/' *> A.decimal)
  <*> skipSpacesAndString "hits:" A.decimal
  <*> skipSpacesAndString "misses:" A.decimal
  <*> skipSpacesAndString "starving:" A.decimal
  <*> skipSpacesAndString "dirty:" A.decimal
  <*> skipSpacesAndString "changed:" A.decimal
  <* A.endOfLine
