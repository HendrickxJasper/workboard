from django.conf import settings


def workboard(request):
    return {"company_name": settings.WORKBOARD_COMPANY_NAME}
