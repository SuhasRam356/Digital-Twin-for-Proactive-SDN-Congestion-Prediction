

class EWMAPredictor:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.history = {}

    def predict(self, link_id, current_utilization):
        """
        Updates the EWMA for the given link and returns the predicted
        utilization for the next time step.
        """
        if link_id not in self.history:
            self.history[link_id] = current_utilization
        else:
            # EWMA formula: S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
            self.history[link_id] = (self.alpha * current_utilization) + ((1 - self.alpha) * self.history[link_id])
        
        # In a simple EWMA, the forecast for t+1 is the smoothed value at t
        predicted = self.history[link_id]
        return round(predicted, 2)
