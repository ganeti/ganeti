{-| HsConstants contains the Haskell constants

This is a transitional module complementary to 'Ganeti.Constants'.  It
is intended to contain the Haskell constants that are meant to be
generated in Python.

Do not write any definitions in this file other than constants.  Do
not even write helper functions.  The definitions in this module are
automatically stripped to build the Makefile.am target
'ListConstants.hs'.  If there are helper functions in this module,
they will also be dragged and it will cause compilation to fail.
Therefore, all helper functions should go to a separate module and
imported.

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
module Ganeti.HsConstants where

-- | Admin states
adminstDown :: String
adminstDown = "down"

-- | Admin states
adminstOffline :: String
adminstOffline = "offline"

-- | Admin states
adminstUp :: String
adminstUp = "up"
