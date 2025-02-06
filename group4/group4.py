"""
**Submitted to ANAC 2024 Automated Negotiation League**
*Team* type your team name here
*Authors* type your team member names with their emails here

This code is free to use or update given that proper attribution is given to
the authors and the ANAC 2024 ANL competition.
"""

from scipy.optimize import curve_fit
import numpy as np
from negmas.outcomes import Outcome
from negmas.sao import ResponseType, SAONegotiator, SAOResponse, SAOState
from negmas.preferences import pareto_frontier, kalai_points, nash_points

class Group4(SAONegotiator):
    """
    Your agent code. This is the ONLY class you need to implement
    """

    rational_outcomes = tuple()
    opponent_outcomes = tuple()
    joint_outcomes = tuple()
    opponent_reserved_value = 0.0

    def on_preferences_changed(self, changes):
        """
        Called when preferences change. In ANL 2024, this is equivalent with initializing the agent.

        Remarks:
            - Can optionally be used for initializing your agent.
            - We use it to save a list of all rational outcomes.

        """
        self.exp = 17.5
        self.offers = []
        self.opponent_ufuns = []
        self.opponent_ufuns_times = []
        self.opponent_exp = []
        self.opponent_strategy = None
        self.next_offer = None
        self.joint_utils = []
        self.pareto_outcomes = []

        # If there a no outcomes (should in theory never happen)
        if self.ufun is None:
            return

        # Get all outcomes that above our reserved value
        self.rational_outcomes = [
            _
            for _ in self.nmi.outcome_space.enumerate_or_sample()  # enumerates outcome space when finite, samples when infinite
            if self.ufun(_) > self.ufun.reserved_value
        ]

        # Get all rational outcomes that on pareto frontier
        pareto_utils, pareto_idx = pareto_frontier([self.ufun, self.opponent_ufun], self.rational_outcomes, sort_by_welfare=True)
        
        if pareto_idx:
            self.pareto_outcomes = [self.rational_outcomes[i] for i in pareto_idx]
            self.pareto_outcomes.sort(key=lambda o: self.ufun(o), reverse=True)

        # find the nash and kalai points and their utilities
        nash = nash_points([self.ufun, self.opponent_ufun], pareto_utils)
        kalai = kalai_points([self.ufun, self.opponent_ufun], pareto_utils)
        nash_idx = nash[0][1]
        kalai_idx = kalai[0][1]

        # save the min offer between kalai or nash
        self.min_offer = (
            self.pareto_outcomes[kalai_idx] if self.ufun(self.pareto_outcomes[kalai_idx]) < self.ufun(self.pareto_outcomes[nash_idx])
            else self.pareto_outcomes[nash_idx]
        )

        # Estimate the reservation value, as a first guess, the opponent has the same reserved_value as you
        self.opponent_outcomes_reserved_value = self.ufun.reserved_value

    def __call__(self, state: SAOState) -> SAOResponse:
        """
        Called to (counter-)offer.

        Args:
            state: the `SAOState` containing the offer from your partner (None if you are just starting the negotiation)
                   and other information about the negotiation (e.g. current step, relative time, etc).
        Returns:
            A response of type `SAOResponse` which indicates whether you accept, or reject the offer or leave the negotiation.
            If you reject an offer, you are required to pass a counter offer.

        Remarks:
            - This is the ONLY function you need to implement.
            - You can access your ufun using `self.ufun`.
            - You can access the opponent's ufun using self.opponent_ufun(offer)
            - You can access the mechanism for helpful functions like sampling from the outcome space using `self.nmi` (returns an `SAONMI` instance).
            - You can access the current offer (from your partner) as `state.current_offer`.
              - If this is `None`, you are starting the negotiation now (no offers yet).
        """
        offer = state.current_offer
        self.treshold = aspiration_function(state.relative_time, 1.0, self.ufun.reserved_value, self.exp) 
        self.update_partner_reserved_value(state)

        # if there are no outcomes (should in theory never happen)
        if self.ufun is None:
            return SAOResponse(ResponseType.END_NEGOTIATION, None)

        # Determine the acceptability of the offer in the acceptance_strategy
        if self.acceptance_strategy(state):
            return SAOResponse(ResponseType.ACCEPT_OFFER, offer)

        # If it's not acceptable, determine the counter offer in the bidding_strategy
        return SAOResponse(ResponseType.REJECT_OFFER, self.bidding_strategy(state))

    def acceptance_strategy(self, state: SAOState) -> bool:
        """
        This is one of the functions you need to implement.
        It should determine whether or not to accept the offer.

        Returns: a bool.
        """
        assert self.ufun
        offer = state.current_offer
        self.next_offer = None

        # rejecting all offers before 90% of the time
        if state.relative_time < 0.9:
            if self.ufun(offer) - self.ufun.reserved_value > (self.opponent_ufun(offer) - self.opponent_reserved_value) * 1.5:
                if abs(self.ufun(offer) - self.ufun(min(self.offers))) < 0.1:
                    return True
            return False
        
        if self.ufun(offer) < self.ufun(self.min_offer):
            if self.nmi.n_steps - state.step > 10:
                return False

        # if offer above tresh, and on pareto -> accept
        if self.ufun(offer) >= self.treshold:
            if offer in self.pareto_outcomes:
                return True
            else:
                # if pareto exists, find the closest offer to the opponent's ufun
                if self.pareto_outcomes:
                    closest = min(
                        self.pareto_outcomes,
                        key = lambda o: abs(self.opponent_ufun(o) - self.opponent_ufun(offer))
                    )
                    # if the closest offer is above the treshold but worse for us, accept the original, else reject and counter offer with closest
                    if self.ufun(closest) >= self.treshold:
                        if self.ufun(offer) >= self.ufun(closest):
                            return True
                        self.next_offer = closest
        return False

    def bidding_strategy(self, state: SAOState) -> Outcome | None:
        """
        This is one of the functions you need to implement.
        It should determine the counter offer.

        Returns: The counter offer as Outcome.
        """
        offer = None
        if self.next_offer is not None:
            offer = self.next_offer
            return self.next_offer
            
        if self.pareto_outcomes:
            if self.ufun(self.pareto_outcomes[0]) < self.treshold:
                offer = self.ufun.best()
            else:
                offer = min(self.pareto_outcomes, key=lambda o: abs(self.ufun(o)-self.treshold)) 
            
        # if no joint outcomes, return the offer best for us
        if offer == None:
            offer = self.pareto_outcomes[0] if self.pareto_outcomes else self.ufun.best()
        
        # if the offer is below nash and kalai, return the min_offer if there are more than 10 steps left.
        if self.ufun(offer) < self.ufun(self.min_offer):
            if self.nmi.n_steps - state.step > 10:
                offer = self.min_offer
        
        # Get offer that is closest to opps min offer, AND above treshold, kalai and nash
        # to do to do

        self.offers.append(offer)
        return offer 
    
    def update_partner_reserved_value(self, state: SAOState) -> None:
        """This is one of the functions you can implement.
        Using the information of the new offers, you can update the estimated reservation value of the opponent.

        returns: None.
        """
        assert self.ufun and self.opponent_ufun

        offer = state.current_offer
        if offer is None:
            return
        
        last_rv = self.opponent_reserved_value
        # update the opponent's ufun and the time it was updated
        self.opponent_ufuns.append(self.opponent_ufun(offer))
        self.opponent_ufuns_times.append(state.relative_time)

        bounds = ((0.2, 0.0), (5.0, min(self.opponent_ufuns)))

        # fitting curve to the opponent's ufuns
        if(len(self.opponent_ufuns) > 5):
            optimal_vals, _ = curve_fit(
                lambda t, e, rv: aspiration_function(t, self.opponent_ufuns[0], rv, e),
                self.opponent_ufuns_times, self.opponent_ufuns, bounds=bounds
            )
            # update the opponent's reserved value based on min between the fitted curve and the min of the opponent's ufuns. min is mainly for fallback.
            self.opponent_reserved_value = min(optimal_vals[1], min(self.opponent_ufuns))
            self.opponent_exp.append(optimal_vals[0])

            # classify the opponent's strategy based on the mean of the last 5 exp values
            avg = np.mean(self.opponent_exp[-5:])
            if avg < 1.0:
                self.opponent_strategy = "Conceder" # is opp strategy needed?
                self.exp = max(avg + 1, self.exp * 0.975)
            else:
                self.opponent_strategy = "Boulware"
                self.exp = avg * 7

        else:
            self.opponent_reserved_value = min(self.opponent_ufuns) / 2

        # update rational_outcomes by removing the outcomes that are below the reservation value of the opponent
        if last_rv < self.opponent_reserved_value:
            # if rv decreased, filter from the complete outcome space
            self.opponent_outcomes = [
                _
                for _ in self.nmi.outcome_space.enumerate_or_sample()  # enumerates outcome space when finite, samples when infinite
                if self.opponent_ufun(_) > self.opponent_reserved_value
            ]
        else:
            self.opponent_outcomes = [
                _
                for _ in self.opponent_outcomes
                if self.opponent_ufun(_) > self.opponent_reserved_value
            ]
        
        # HOW DO WE USE THE JOINT OUTCOMES? Should we?

        # get a list of both outcomes intersection
        self.joint_outcomes = list(set(self.pareto_outcomes) & set(self.opponent_outcomes))
        
        if not self.joint_outcomes:
            self.joint_outcomes = self.pareto_outcomes

        # sort the joint outcomes based on the utility function
        self.joint_outcomes.sort(key=lambda o: self.ufun(o), reverse=True)

# Helper functions
def aspiration_function(t, mx, rv, e):
    """A monotonically decrasing curve starting at mx (t=0) and ending at rv (t=1)"""
    return (mx-rv) * (1.0 -np.power(t, e)) + rv

# if you want to do a very small test, use the parameter small=True here. Otherwise, you can use the default parameters.
if __name__ == "__main__":
    from .helpers.runner import run_a_tournament

    run_a_tournament(Group4, small=True, debug=True)
