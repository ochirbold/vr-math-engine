"""Terminate an entire compute process on wall timeout, including native solver work."""
import multiprocessing
from .contracts import ExecutionRequest, PredictionRequest


def _child(connection, payload, operation):
    try:
        from .engine import execute
        from .expressions import ModelError
        try:
            if operation == "predict":
                from .statistics import predict
                result = predict(PredictionRequest.model_validate(payload))
            elif operation == "execute":
                result = execute(ExecutionRequest.model_validate(payload))
            else:
                raise ModelError("Unknown compute operation")
            connection.send({"result": result.model_dump()})
        except (ModelError, ValueError) as exc:
            connection.send({"error": str(exc), "invalid_model": True})
    except Exception as exc:
        connection.send({"error": f"Execution failed: {type(exc).__name__}", "invalid_model": False})
    finally:
        connection.close()


def execute_isolated(payload, timeout=90, operation="execute"):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(child, payload, operation))
    process.start()
    child.close()
    try:
        if not parent.poll(timeout):
            return {"error": "Execution wall timeout", "timeout": True}
        try:
            return parent.recv()
        except EOFError:
            return {"error": "Compute process exited without a result"}
    finally:
        parent.close()
        process.join(1)
        if process.is_alive():
            process.terminate()
            process.join(3)
        if process.is_alive():
            process.kill()
            process.join()
        process.close()
