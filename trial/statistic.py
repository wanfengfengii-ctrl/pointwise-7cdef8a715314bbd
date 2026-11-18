def validate_response(response):
    if type(response) is not int or response not in (0, 1):
        raise ValueError('response must be an integer 0 or 1')
    return response


def signed_successes(assignments, responses):
    if len(assignments) != len(responses):
        raise ValueError('assignment and response lengths differ')
    statistic = 0
    for assignment, response in zip(assignments, responses, strict=True):
        if type(assignment) is not str or assignment not in ('A', 'B'):
            raise ValueError('assignment must be A or B')
        response = validate_response(response)
        statistic += response if assignment == 'A' else -response
    return statistic
