import json
import os

import boto3
from aws_xray_sdk.core import patch, xray_recorder
from botocore.exceptions import ClientError

patched_libs = ('boto3',)
patch(patched_libs)


session = boto3.Session()
sns = session.client("sns")
booking_sns_topic = os.getenv("BOOKING_TOPIC")


class BookingNotificationException(Exception):
    pass


def notify_booking(payload, booking_reference):
    """Notify whether a booking have been processed successfully

    Parameters
    ----------
    payload: dict
        Payload to be sent as notification

        customerId: string
            Unique Customer ID

        price: string
            Flight price

    booking_reference: string
        Confirmed booking reference    

    Returns
    -------
    dict
        notificationId: string
            Unique ID confirming notification delivery

    Raises
    ------
    BookingNotificationException
        Booking Notification Exception including error message upon failure
    """

    successful_subject = f"Booking confirmation for {booking_reference}"
    unsuccessful_subject = f"Unable to process booking for {booking_reference}"

    subject = successful_subject if booking_reference else unsuccessful_subject
    booking_status = "confirmed" if booking_reference else "cancelled"

    try:
        with xray_recorder.capture('notify_booking') as subsegment:
            subsegment.put_annotation("BookingReference", booking_reference)

            ret = sns.publish(
                TopicArn=booking_sns_topic,
                Message=json.dumps(payload),
                Subject=subject,
                MessageAttributes={
                    "Booking.Status": {"DataType": "String", "StringValue": booking_status}
                },
            )

            message_id = ret["MessageId"]
            subsegment.put_annotation("BookingNotification", message_id)
            subsegment.put_metadata(booking_reference, ret, "notification")

        return {"notificationId": message_id}
    except ClientError as e:
        raise BookingNotificationException(e.response["Error"]["Message"])


@xray_recorder.capture('handler')
def lambda_handler(event, context):
    """AWS Lambda Function entrypoint to notify booking

    Parameters
    ----------
    event: dict, required
        Step Functions State Machine event

        customer_id: string
            Unique Customer ID

        price: string
            Flight price

        bookingReference: string
            Confirmed booking reference

    context: object, required
        Lambda Context runtime methods and attributes
        Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    -------
    string
        notificationId
            Unique ID confirming notification delivery

    Raises
    ------
    BookingNotificationException
        Booking Notification Exception including error message upon failure
    """

    customer_id = event.get("customerId", False)
    price = event.get("payment", False).get("price", False)  # ['payment']['price'] w/ defaults if either is empty/undefined

    booking_reference = event.get("bookingReference", False)

    if not customer_id and not price:
        raise ValueError("Invalid customer and price")

    try:
        payload = {"customerId": customer_id, "price": price}
        ret = notify_booking(payload, booking_reference)
    except BookingNotificationException as e:
        raise BookingNotificationException(e)

    # Step Functions use the return to append `notificationId` key into the overall output
    return ret["notificationId"]
