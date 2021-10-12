"""
Multithread or Multiprocess Engine
==================================
"""
import logging as helmscanner_logging
import concurrent.futures 
import math
import os
from queue import Queue
from threading import Thread

def multiprocessit(
    func, key, list, num_of_workers = None
):
    if not num_of_workers:
        num_of_workers = math.ceil(os.cpu_count() / 2)
        helmscanner_logging.INFO(f"MultiThreader: Creating {num_of_workers} MP workers from {os.cpu_count()}")
    if num_of_workers > 0:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_of_workers) as executor:
            futures = {executor.submit(func, key, item): item for item in list}
            wait_result = concurrent.futures.wait(futures)
            if wait_result.not_done:
                raise Exception(f"failed to perform {func.__name__}")
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    raise e

def multithreadit(
    func, key, list, scannerObject, num_of_workers = None
):
    if not num_of_workers:
        num_of_workers = math.ceil(os.cpu_count() * 0.7)
        #helmscanner_logging.INFO(f"MultiThreader: Creating {num_of_workers} MT workers")
    if num_of_workers > 0:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_of_workers) as executor:
            futures = {executor.submit(func, key, item, scannerObject): item for item in list}
            wait_result = concurrent.futures.wait(futures)
            if wait_result.not_done:
                raise Exception(f"failed to perform {func.__name__}")
            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    raise e

single_queue_num_of_workers = math.ceil(os.cpu_count() * 0.7)
#helmscanner_logging.INFO(f"MultiThreader: Creating {single_queue_num_of_workers} MT workers from {os.cpu_count()}")
singleJobQueueExecutor = concurrent.futures.ThreadPoolExecutor(max_workers=single_queue_num_of_workers)
jobQueue = Queue(maxsize=0)

def singleJobQueueIt(
    func, threadArgs
):
    jobQueue.put({"func":func, "args": threadArgs})
    if single_queue_num_of_workers > 0:
        for i in range(single_queue_num_of_workers):
            job = jobQueue.get()
            worker = Thread(target=job['func'], args=job['args'])
            worker.setDaemon(True)
            worker.start()

def getJobQueue():
    return jobQueue
    
    # We need this to always accept new jobs, where is the block going to happen? 
    # We may need to change from the suggested info here: https://www.troyfawkes.com/learn-python-multithreading-queues-basics/
    # As calling singleJobQueueIt may need to "refresh" the processing (as we'll be calling this each time we add something anyway).
    

# def do_stuff(q):
#   while True:
#     print q.get()
#     q.task_done()


# for i in range(num_threads):
#   worker = Thread(target=do_stuff, args=(q,))
#   worker.setDaemon(True)
#   worker.start()

# for x in range(100):
#   q.put(x)

# q.join()