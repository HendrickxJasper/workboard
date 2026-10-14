from procrastinate.contrib.django import app

from . import services


@app.task(queue="agent", name="agent.run_agent")
def run_agent(run_id: int):
    services.execute_run(run_id)


@app.periodic(cron="*/5 * * * *", periodic_id="reap_stale_runs")
@app.task(queueing_lock="reap_stale_runs", name="agent.reap_stale_runs")
def reap_stale_runs(timestamp: int):
    services.reap_stale_runs()
