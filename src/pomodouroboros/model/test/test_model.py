from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Type, TypeVar
from unittest import TestCase
from unittest.mock import ANY
from zoneinfo import ZoneInfo

from datetype import aware
from twisted.internet.interfaces import IReactorTime
from twisted.internet.task import Clock

from ..boundaries import EvaluationResult, PomStartResult, UIEventListener
from ..debugger import debug
from ..ideal import idealScore
from ..intention import Estimate, Intention
from ..intervals import (
    AnyIntervalOrIdle,
    Break,
    Evaluation,
    GracePeriod,
    Idle,
    Pomodoro,
    StartPrompt,
)
from ..nexus import Nexus
from ..observables import Changes, IgnoreChanges, SequenceObserver
from ..sessions import DailySessionRule, Weekday, Session


@dataclass
class TestInterval:
    """
    A record of methods being called on L{TestUserInterface}
    """

    interval: AnyIntervalOrIdle
    actualStartTime: float | None = None
    actualEndTime: float | None = None
    currentProgress: list[float] = field(default_factory=list)


T = TypeVar("T")


@dataclass
class TestUserInterface:
    """
    Implementation of all UIEventListener protocols.
    """

    theNexus: Nexus = field(init=False)
    clock: IReactorTime
    actions: list[TestInterval] = field(default_factory=list)
    actualInterval: TestInterval | None = None

    def describeCurrentState(self, description: str) -> None: ...

    def intervalProgress(self, percentComplete: float) -> None:
        """
        The active interval has progressed to C{percentComplete} percentage
        complete.
        """
        debug("interval: progress!", percentComplete)
        assert self.actualInterval is not None
        self.actualInterval.currentProgress.append(percentComplete)

    def intervalStart(self, interval: AnyIntervalOrIdle) -> None:
        """
        An interval has started, record it.
        """
        debug("interval: start!", interval)
        assert not (
            self.actions and self.actions[0].interval is interval
        ), f"sanity check: no double-starting ({interval}): {self.actions}"
        it = self.actualInterval = TestInterval(interval, self.clock.seconds())
        if isinstance(interval, Idle):
            return
        self.actions.append(it)

    def intervalEnd(self) -> None:
        """
        The interval has ended. Hide the progress bar.
        """
        assert self.actualInterval is not None
        self.actualInterval.actualEndTime = self.clock.seconds()

    def intentionListObserver(self) -> SequenceObserver[Intention]:
        """
        Return a change observer for the full list of L{Intention}s.
        """
        return IgnoreChanges

    def intentionObjectObserver(
        self, intention: Intention
    ) -> Changes[str, object]:
        """
        Return a change observer for the given L{Intention}.
        """
        return IgnoreChanges

    def intentionPomodorosObserver(
        self, intention: Intention
    ) -> SequenceObserver[Pomodoro]:
        """
        Return a change observer for the given L{Intention}'s list of
        pomodoros.
        """
        return IgnoreChanges

    def intentionEstimatesObserver(
        self, intention: Intention
    ) -> SequenceObserver[Estimate]:
        """
        Return a change observer for the given L{Intention}'s list of
        estimates.
        """
        return IgnoreChanges

    def intervalObserver(
        self, interval: AnyIntervalOrIdle
    ) -> Changes[str, object]:
        """
        Return a change observer for the given C{interval}.
        """
        return IgnoreChanges

    # testing methods

    def setIt(self, nexus: Nexus) -> UIEventListener:
        self.theNexus = nexus
        return self

    def clear(self) -> None:
        """
        Clear the actions log so we can assert about just the interesting
        parts.
        """
        filtered = [
            action for action in self.actions if action.actualEndTime is None
        ]
        self.actions[:] = filtered


intention: Type[UIEventListener] = TestUserInterface


class NexusTests(TestCase):
    """
    Nexus tests.
    """

    userMode: Nexus

    def setUp(self) -> None:
        """
        Set up this test case.
        """
        self.maxDiff = 9999
        self.clock = Clock()
        self.testUI = TestUserInterface(self.clock)
        self.nexus = Nexus(self.testUI.setIt, 0)

    def advanceTime(self, n: float) -> None:
        """
        Advance the virtual timestamp of this test to the current time + C{n}
        where C{n} is a number of seconds.
        """
        debug("test is advancing", n)
        self.clock.advance(n)
        now = self.clock.seconds()
        debug("test advancing model to", now)
        self.nexus.advanceToTime(now)
        debug("model advanced", self.nexus._lastUpdateTime)

    def test_noPointsForNothing(self) -> None:
        """
        Measuring the score of an empty period of time should produce no
        points.
        """

        def checkScore() -> float:
            return sum(
                (
                    each.points
                    for each in self.nexus.scoreEvents(
                        startTime=self.clock.seconds(),
                        endTime=self.clock.seconds() + 1000.0,
                    )
                ),
                start=0.0,
            )

        self.assertEqual(checkScore(), 0)
        self.advanceTime(1)
        a = self.nexus.addIntention("new 1")
        self.advanceTime(1)
        self.assertEqual(checkScore(), 0)
        self.nexus.addIntention("new 2")
        self.advanceTime(1)
        self.nexus.startPomodoro(a)
        pom = a.pomodoros[0]
        self.advanceTime(pom.endTime - self.clock.seconds())
        self.nexus.evaluatePomodoro(pom, EvaluationResult.achieved)
        self.advanceTime(10)
        self.assertEqual(checkScore(), 0)

    def test_idealScoreNotifications(self) -> None:
        """
        When the user has a session started, they will receive notifications
        telling them about decreases to their potential maximum score.
        """
        sessionStart = 1000
        realTimeStartDelay = 100.0
        self.nexus.addManualSession(sessionStart, 2000)
        self.advanceTime(sessionStart + realTimeStartDelay)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(1.0)
        self.advanceTime(197.0)
        self.advanceTime(100.0)
        self.advanceTime(103.0)

        self.assertEqual(
            [
                TestInterval(
                    interval=StartPrompt(
                        startTime=1100.0,
                        endTime=1400.0,
                        pointsBeforeLoss=21.25,
                        pointsAfterLoss=15.25,
                    ),
                    actualStartTime=1100.0,
                    actualEndTime=1402.0,
                    currentProgress=[
                        0.0,
                        0.0033333333333333335,
                        0.006666666666666667,
                        0.01,
                        0.013333333333333334,
                        0.016666666666666666,
                        0.6733333333333333,
                        1.0,
                    ],
                ),
                TestInterval(
                    interval=StartPrompt(
                        startTime=1402.0,
                        endTime=1700.0,
                        pointsBeforeLoss=15.25,
                        pointsAfterLoss=4.0,
                    ),
                    actualStartTime=1402.0,
                    actualEndTime=None,
                    currentProgress=[0.0, 0.34563758389261745],
                ),
            ],
            self.testUI.actions,
        )

    def test_startDuringSession(self) -> None:
        """
        When a session is running (and therefore, a 'start' prompt /
        score-decrease timer interrval is running) starting a pomodoro stops
        that timer and begins a pomodoro.
        """
        intention = self.nexus.addIntention("x")
        self.nexus.addManualSession(1000, 2000)
        self.advanceTime(100)  # no-op; time before session
        self.advanceTime(1000)  # enter session
        self.advanceTime(50)  # time in session before pomodoro
        self.nexus.startPomodoro(intention)
        self.advanceTime(120)  # enter pomodoro
        self.assertEqual(
            [
                TestInterval(
                    interval=StartPrompt(
                        startTime=1100.0,
                        endTime=1400.0,
                        pointsBeforeLoss=21.25,
                        pointsAfterLoss=15.25,
                    ),
                    actualStartTime=1100.0,
                    actualEndTime=1150.0,
                    currentProgress=[
                        0.0,
                        50.0 / 300.0,
                        1.0,
                    ],
                ),
                TestInterval(
                    interval=Pomodoro(
                        intention=intention,
                        startTime=1150.0,
                        endTime=1150.0 + (5.0 * 60.0),
                        indexInStreak=0,
                    ),
                    actualStartTime=1150.0,
                    actualEndTime=None,
                    currentProgress=[
                        0.0,
                        120 / (5 * 60.0),
                    ],
                ),
            ],
            self.testUI.actions,
        )

    def test_idealScore(self) -> None:
        """
        The ideal score should be the best sequence of events that the user
        could execute.
        """
        self.advanceTime(1000)
        ideal1 = idealScore(self.nexus, 1000.0, 2000.0)
        self.assertEqual(ideal1.nextPointLoss, 1400.0)
        pointsForCreatingFirstIntention = 3.0
        pointsForBreak = 1.0
        pointsForSecondIntentionSet = 2.0
        self.assertEqual(
            ideal1.pointsLost(),
            pointsForBreak
            + pointsForSecondIntentionSet
            + pointsForCreatingFirstIntention,
        )
        self.advanceTime(1600)
        ideal2 = idealScore(self.nexus, 1000.0, 2000.0)
        self.assertEqual(ideal2.nextPointLoss, None)
        self.assertEqual(ideal2.pointsLost(), 0.0)
        # The perfect score is the same as the ideal score at the very
        # beginning of the session.
        self.assertEqual(
            ideal1.perfectScore.totalScore, ideal2.perfectScore.totalScore
        )

    def test_exactAdvance(self) -> None:
        """
        If you advance to exactly the boundary between pomodoro and break it
        should work ok.
        """

        self.advanceTime(5.0)
        i = self.nexus.addIntention("i")
        self.nexus.startPomodoro(i)
        self.advanceTime(5 * 60.0)
        self.assertEqual(
            [
                TestInterval(
                    Pomodoro(5.0, i, 5 + 5.0 * 60, indexInStreak=0),
                    actualStartTime=5.0,
                    actualEndTime=(5.0 + 5 * 60),
                    currentProgress=[0.0, 1.0],
                ),
                TestInterval(
                    Break(5 + 5.0 * 60, 5 + (5 * 60.0 * 2)),
                    actualStartTime=5 + 5.0 * 60,
                    actualEndTime=None,
                    currentProgress=[0.0],
                ),
            ],
            self.testUI.actions,
        )

    def test_advanceToNewSession(self) -> None:
        """
        A nexus should start a new session automatically when its rules say
        it's time to do that.
        """
        TZ = ZoneInfo("America/Los_Angeles")
        dailyStart = aware(
            time(hour=9, minute=30, tzinfo=TZ),
            ZoneInfo,
        )
        dailyEnd = aware(
            time(hour=4 + 12, minute=45, tzinfo=TZ),
            ZoneInfo,
        )
        self.nexus._sessionRules.append(
            DailySessionRule(
                dailyStart,
                dailyEnd,
                {Weekday.monday, Weekday.wednesday, Weekday.thursday},
            )
        )
        now = aware(datetime(2024, 5, 8, 11, tzinfo=TZ), ZoneInfo)
        self.nexus.advanceToTime(now.timestamp())

        # TODO: try to observe the creation of this session in the way that the
        # UI would
        self.assertEqual(
            self.nexus._sessions[:],
            [Session(start=1715185800.0, end=1715211900.0, automatic=True)],
        )

        # note that I definitely cheated a little bit with these data
        # structures and copied them out of the observed output of the code, I
        # didn't hand-calculate that it's 1500 seconds to the next score drop
        promptStart = 1715191200.0
        promptStop = 1715192700.0
        self.assertEqual(
            [
                TestInterval(
                    interval=StartPrompt(
                        startTime=promptStart,
                        endTime=promptStop,
                        pointsBeforeLoss=ANY,
                        pointsAfterLoss=ANY,
                    ),
                    actualStartTime=0.0,
                    actualEndTime=None,
                    currentProgress=[0.0],
                )
            ],
            self.testUI.actions,
        )
        self.nexus.advanceToTime(now.timestamp() + 20)
        self.assertEqual(
            [
                TestInterval(
                    interval=StartPrompt(
                        startTime=1715191200.0,
                        endTime=1715192700.0,
                        pointsBeforeLoss=ANY,
                        pointsAfterLoss=ANY,
                    ),
                    actualStartTime=0.0,
                    actualEndTime=None,
                    currentProgress=[0.0, (20 / (promptStop - promptStart))],
                )
            ],
            self.testUI.actions,
        )

    def test_story(self) -> None:
        """
        Full story testing various features of a day of using Pomodouroboros.
        """
        # TODO: obviously a big omnibus thing like this is not good, but this
        # was a combination of bootstrapping the tests working through the
        # nexus's design.  Split it up later.

        # Some time passes before intentions are added.  Nothing should really
        # happen (but if we add a discrete timestamp for logging intention
        # creations, this will be when it is).
        self.advanceTime(1000)

        # User types in some intentions and sets estimates for some of them
        # TBD: should there be a prompt?
        first = self.nexus.addIntention("first intention", estimate=100.0)
        second = self.nexus.addIntention("second intention")
        third = self.nexus.addIntention("third intention", estimate=50.0)
        self.assertEqual(self.nexus.intentions, [first, second, third])
        # TODO:
        # self.assertEqual(self.nexus.intentions, self.testUI.sawIntentions)

        # Some time passes so we can set a baseline for pomodoro timing
        # (i.e. our story doesn't start at time 0).
        self.advanceTime(3000)

        # Start our first pomodoro with our first intention.
        self.assertEqual(
            self.nexus.startPomodoro(first), PomStartResult.Started
        )
        self.assertEqual(first.pomodoros, [self.testUI.actions[0].interval])

        # No time has passed. We can't start another pomodoro; the first one is
        # already running.
        self.assertEqual(
            self.nexus.startPomodoro(second), PomStartResult.AlreadyStarted
        )
        self.assertEqual(second.pomodoros, [])

        # Advance time 3 times, creating 3 records of progress.
        self.advanceTime(1)
        self.advanceTime(1)
        self.advanceTime(1)

        # We expect our first pomodoro to be 5 minutes long.
        expectedDuration = 5 * 60
        expectedFirstPom = Pomodoro(
            startTime=4000.0,
            endTime=4000.0 + expectedDuration,
            intention=first,
            indexInStreak=0,
        )
        self.assertEqual(
            [
                TestInterval(
                    expectedFirstPom,
                    actualStartTime=4000.0,
                    actualEndTime=None,
                    currentProgress=[0.0]
                    + [(each / expectedDuration) for each in [1, 2, 3]],
                )
            ],
            self.testUI.actions,
        )

        # Advance past the end of the pomodoro, into a break.
        self.advanceTime((5 * 60) + 1)

        # This is the break we expect to see; also 5 minutes.
        expectedBreak = Break(startTime=4300.0, endTime=4600.0)
        self.assertEqual(
            [
                TestInterval(
                    expectedFirstPom,
                    actualStartTime=4000.0,
                    actualEndTime=4304.0,
                    currentProgress=[
                        0.0,
                        *[(each / expectedDuration) for each in [1, 2, 3]],
                        1.0,
                    ],
                ),
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=None,
                    currentProgress=[0.0, 4 / expectedDuration],
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # Move past the end of the break, into a grace period at the beginning
        # of the next pomodoro.
        self.advanceTime(10)
        self.assertEqual(
            [
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=None,
                    currentProgress=[0.0]
                    + [(each / expectedDuration) for each in [4, 14]],
                ),
            ],
            self.testUI.actions,
        )

        # Advance into the grace period, but not past the end of the grace
        # period
        self.advanceTime((5 * 60) - 13)
        expectedGracePeriod = GracePeriod(4600.0, 5200.0)
        self.assertEqual(
            [
                TestInterval(
                    expectedBreak,
                    actualStartTime=4304.0,
                    actualEndTime=4300.0 + (5.0 * 60.0) + 1,  # break is over
                    currentProgress=[
                        0.0,
                        *[(each / expectedDuration) for each in [4, 14]],
                        1.0,
                    ],
                ),
                TestInterval(
                    expectedGracePeriod,
                    actualStartTime=4601.0,
                    currentProgress=[0.0]
                    + [
                        each
                        / (
                            expectedGracePeriod.endTime
                            - expectedGracePeriod.startTime
                        )
                        for each in [1]
                    ],
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()
        # Advance past the end of the grace period.
        self.advanceTime(10 * 60)
        self.assertEqual(
            [
                TestInterval(
                    expectedGracePeriod,
                    actualStartTime=4601.0,
                    currentProgress=[
                        0.0,
                        *(
                            each
                            / (
                                expectedGracePeriod.endTime
                                - expectedGracePeriod.startTime
                            )
                            for each in [1]
                        ),
                        1.0,
                    ],
                    actualEndTime=5201.0,  # Grace period is over.
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # Advance really far to offset our second streak.
        self.advanceTime(5000)
        # Nothing happens despite the >80 minutes passing, as time is advancing
        # outside of a streak or session.
        self.assertEqual([], self.testUI.actions)

        # OK, start a second streak.
        self.assertEqual(
            self.nexus.startPomodoro(second), PomStartResult.Started
        )

        # Advance past the end of the pomodoro, into the break.
        self.advanceTime((5 * 60) + 1.0)
        # Try to start a second pomodoro during the break; you can't. You're on
        # a break.
        self.assertEqual(
            self.nexus.startPomodoro(second), PomStartResult.OnBreak
        )
        # Advance out of the end of the break, into the next pomodoro
        self.advanceTime((5 * 60) + 1.0)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=10201.0,
                        intention=second,
                        endTime=10501.0,
                        indexInStreak=0,
                    ),
                    actualStartTime=10201.0,
                    actualEndTime=10502.0,
                    # No progress, since we skipped the whole thing.
                    currentProgress=[0.0, 1.0],
                ),
                TestInterval(
                    interval=Break(startTime=10501.0, endTime=10801.0),
                    actualStartTime=10502.0,
                    actualEndTime=10803.0,
                    # Jumped in right at the beginning, went way out past the
                    # end
                    currentProgress=[0.0, 0.0033333333333333335, 1.0],
                ),
                TestInterval(
                    interval=GracePeriod(
                        startTime=10801.0, originalPomEnd=11401.0
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,
                    # Grace period has just started, it has not ended yet
                    currentProgress=[0.0, 0.01],
                ),
            ],
            self.testUI.actions,
        )
        self.testUI.clear()

        # For the first time we're starting a pomdoro from *within* a grace
        # period, so we are continuing a streak.
        self.assertEqual(
            self.nexus.startPomodoro(third), PomStartResult.Continued
        )
        self.assertEqual(
            [
                TestInterval(
                    interval=GracePeriod(
                        startTime=10801.0, originalPomEnd=11401.0
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,  # period should probably end before pom starts
                    currentProgress=[0.0, 0.01],
                ),
                TestInterval(
                    interval=Pomodoro(
                        startTime=10801.0,  # the "start time" of the pomodoro
                        # actually *matches* that of the
                        # grace period.
                        intention=third,
                        endTime=11401.0,
                        indexInStreak=1,
                    ),
                    actualStartTime=10803.0,
                    actualEndTime=None,
                    currentProgress=[0.0],
                ),
            ],
            self.testUI.actions,
        )

        # test for scoring
        events = list(self.nexus.scoreEvents())

        # currently the score is 1 point for the first pomdoro in a streak and
        # 4 points for the second
        points_for_first_interval = 1
        points_for_second_interval = 2
        points_for_intention = 3
        points_for_estimation = 1
        points_for_break = 1.0

        self.assertEqual(
            sum(each.points for each in events),
            # 2 first-in-streak pomodoros, 1 second-in-streak
            (points_for_first_interval * 2)
            + (points_for_second_interval)
            + (3 * points_for_intention)
            + (2 * points_for_estimation)
            + (2 * points_for_break),
        )

        from json import dumps, loads

        from ..storage import nexusFromJSON, nexusToJSON

        self.nexus.intentions[-1].abandoned = True
        roundTrip = nexusFromJSON(
            loads(dumps(nexusToJSON(self.nexus))),
            lambda nexus: self.nexus.userInterface,
        )
        self.maxDiff = 99999
        self.assertEqual(self.nexus._intentions, roundTrip._intentions)
        self.assertEqual(self.nexus._activeInterval, roundTrip._activeInterval)
        self.assertEqual(self.nexus._lastUpdateTime, roundTrip._lastUpdateTime)
        self.assertEqual(
            list(self.nexus.cloneWithoutUI()._upcomingDurations),
            list(roundTrip.cloneWithoutUI()._upcomingDurations),
        )
        self.assertEqual(self.nexus._streakRules, roundTrip._streakRules)
        self.assertEqual(
            self.nexus._previousStreaks, roundTrip._previousStreaks
        )
        self.assertEqual(self.nexus._currentStreak, roundTrip._currentStreak)
        self.assertEqual(self.nexus._sessions, roundTrip._sessions)

    def test_achievedEarly(self) -> None:
        """
        If I achieve the desired intent of a pomodoro while it is still
        running, that pomodoro should really be marked as done, and the next
        break should start immediately.
        """
        START_TIME = 1234.0
        self.advanceTime(START_TIME)

        intent = self.nexus.addIntention("early completion intention")

        self.assertEqual(
            self.nexus.startPomodoro(intent), PomStartResult.Started
        )

        DEFAULT_DURATION = 5.0 * 60.0
        EARLY_COMPLETION = DEFAULT_DURATION / 3

        self.advanceTime(EARLY_COMPLETION)
        action = self.testUI.actions[0].interval
        assert isinstance(action, Pomodoro), f"{action}"
        self.assertEqual(self.nexus.availableIntentions, [intent])
        # TODO:
        # self.assertEqual(self.testUI.completedIntentions, [])
        self.nexus.evaluatePomodoro(action, EvaluationResult.achieved)
        self.assertEqual(self.nexus.availableIntentions, [])
        # TODO:
        # self.assertEqual(self.testUI.completedIntentions, [intent])
        self.advanceTime(1)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=START_TIME,  # the "start time" of the pomodoro
                        # actually *matches* that of the
                        # grace period.
                        intention=intent,
                        endTime=START_TIME + EARLY_COMPLETION,
                        evaluation=Evaluation(
                            EvaluationResult.achieved,
                            START_TIME + EARLY_COMPLETION,
                        ),
                        indexInStreak=0,
                    ),
                    actualStartTime=START_TIME,
                    actualEndTime=START_TIME + EARLY_COMPLETION,
                    currentProgress=[0.0, 1 / 3, 1.0],
                ),
                TestInterval(
                    interval=Break(
                        startTime=START_TIME + EARLY_COMPLETION,
                        endTime=START_TIME
                        + EARLY_COMPLETION
                        + DEFAULT_DURATION,
                    ),
                    actualStartTime=START_TIME + EARLY_COMPLETION,
                    actualEndTime=None,
                    # Jumped in right at the beginning, went way out past the
                    # end
                    currentProgress=[
                        0.0,  # is this desirable?
                        0.0033333333333333335,
                    ],
                ),
            ],
            self.testUI.actions,
        )

    def test_evaluatedNotAchievedEarly(self) -> None:
        """
        Evaluating an ongoing pomodoro as some other status besides 'achieved'
        will not stop it early.
        """
        START_TIME = 1234.0
        self.advanceTime(START_TIME)

        intent = self.nexus.addIntention("early completion intention")

        self.assertEqual(
            self.nexus.startPomodoro(intent), PomStartResult.Started
        )

        DEFAULT_DURATION = 5.0 * 60.0
        EARLY_COMPLETION = DEFAULT_DURATION / 3

        self.advanceTime(EARLY_COMPLETION)
        action = self.testUI.actions[0].interval
        assert isinstance(action, Pomodoro)
        self.nexus.evaluatePomodoro(action, EvaluationResult.distracted)
        self.advanceTime(1)
        self.assertEqual(
            [
                TestInterval(
                    interval=Pomodoro(
                        startTime=START_TIME,
                        intention=intent,
                        endTime=START_TIME + DEFAULT_DURATION,
                        evaluation=Evaluation(
                            EvaluationResult.distracted,
                            START_TIME + EARLY_COMPLETION,
                        ),
                        indexInStreak=0,
                    ),
                    actualStartTime=START_TIME,
                    actualEndTime=None,
                    currentProgress=[0.0, 1 / 3, (1.0 / 3) + (1 / (5.0 * 60))],
                ),
            ],
            self.testUI.actions,
        )

    def test_evaluationScore(self) -> None:
        """
        Evaluating a pomdooro as focused on an intention should give us 1 point.
        """
        self.advanceTime(1)
        intent = self.nexus.addIntention("intent")
        self.nexus.startPomodoro(intent)
        self.advanceTime((5 * 60.0) + 1)
        pom = self.testUI.actions[0].interval
        assert isinstance(pom, Pomodoro)

        def currentPoints() -> float:
            events = list(self.nexus.scoreEvents())
            debug([(each, each.points) for each in events])
            return sum(each.points for each in events)

        before = currentPoints()
        self.nexus.evaluatePomodoro(pom, EvaluationResult.focused)
        after = currentPoints()
        self.assertEqual(after - before, 1.0)
