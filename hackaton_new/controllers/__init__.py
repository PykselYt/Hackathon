def make_controller(name: str, cfg: dict, model_path: str | None = None):
    """name: fixed | max_pressure | ppo"""
    if name == "fixed":
        from controllers.fixed import FixedController
        return FixedController(cfg)
    if name == "max_pressure":
        from controllers.max_pressure import MaxPressureController
        return MaxPressureController(cfg)
    if name == "ppo":
        from controllers.ppo import PPOController
        return PPOController(cfg, model_path)
    raise ValueError(f"unknown controller: {name}")
