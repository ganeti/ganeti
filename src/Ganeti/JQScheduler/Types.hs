{-# LANGUAGE TemplateHaskell #-}
{-| Types for the JQScheduler.

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

module Ganeti.JQScheduler.Types where

import System.INotify

import Ganeti.JQueue as JQ
import Ganeti.Lens hiding (chosen)
import Ganeti.Utils

data JobWithStat = JobWithStat { jINotify :: Maybe INotify
                               , jStat :: FStat
                               , jJob :: QueuedJob
                               }

$(makeCustomLenses' ''JobWithStat ['jJob])

data Queue = Queue { qEnqueued :: [JobWithStat]
                   , qRunning :: [JobWithStat]
                   , qManipulated :: [JobWithStat] -- ^ running jobs that are
                                                   -- being manipulated by
                                                   -- some thread
                   }

$(makeCustomLenses ''Queue)
