# Introduction 

A non-competitive cycling tour is conducted every year. This involves pre-registration and registration of riders for the year's tour. During the tour ride and rider management. Apps will be developed for these use cases. Apart from these there can be data analysis and reports generation. For all these purposes data are needed. Since data is being shared across apps it needs to be maintained centrally. This document provides the data requirements.

Main purpose of this project is to provide a deployable solution which can create AWS resources like DynamoDB Tables, Lambda functions, API, etc. that are meant to be used by other apps within the tour eco-system. This is essentially creating the backend required for the tour management.

> [!IMPORTANT] All resources created will be specific to an AWS Account and nothing can be shared between any account i.e. completed isolated and no sharing of data can be possible. This must be adhered to at all times.

# Use Cases
## Pre-Tour
Pre-registration and registration are the key activities before the tour can commence apart from other preparation and arrangements. Pre-registration is asking riders who are interested to participate in the tour. After cut-off a review is carried out by the tour organizers to select riders for the up coming tour. Pre-registered riders who are selected to participate in the tour will be notified. These qualified riders will take next actions (payment for one) and register for the tour.

For now this process is completely manual and only some tour data prepared from this process is uploaded to tour database before the tour commences. Otherwise this process is out of scope.

## Check-In App
An application, let's refer it as Check-in App is available for use during the tour to manage daily rides and track riders in each ride. This app will be used by Cycling Tour administrators, pit stop team and optionally by hotel front desk staff to check-in riders at various stages of the daily ride - Start - Flag Off, Pit Stop(s) and Finish.

Pit stop users will be provisioned as pre-defined Cognito roles `PS_1_USER` to `PS_5_USER`. These roles are meant only for `PIT_STOP` stages and each role maps to the same stage number as its suffix: `PS_1_USER` → stage 1, `PS_2_USER` → stage 2, and so on. Stage `0` is always `START`, the last stage is always `FINISH`, and `FINISH` must never be associated with a pit stop role. A user may hold more than one `PS_<n>_USER` role.

This app will have 2 primary features:  
1. Dashboard - for Ride progress & Rider tracking  
1. Rider Check-In  

Apart from these following Admin features will also be available.  
1. Add/Modify Ride
1. Close Ride
1. Open/Close Pit Stop stage

To understand how the data is used refer to the following document from Check-In App project.
 - [App Requirements](https://github.com/kvijay77-in/tour-mgmt-app/blob/main/docs/Requirements.md)
 - [Dashboard Feature](https://github.com/kvijay77-in/tour-mgmt-app/blob/main/docs/Dashboard-Feature.md)

## Rider App
This is a future roadmap item. This App is for riders to use for pre-registration, registration and during the actual tour with a small part for rider tracking as a self-service. It's only in ideation stage and no design or development has been taken up yet.

## Excel Report
Data can be extracted during various of the tour starting from pre-registration to post-tour analysis to Excel. This data can be used for all external (out side of the Apps capability) activities and to prepare reports. No tool or development has been done yet.

# Data Set

Following are expected to be maintained in one or more DynamoDB tables. Tour Riders, Ride Detail, Check-In registry and User Profile are considered tour data and should be managed per tour which will make data management easy. Tour Entity design is expected to be part of data model design phase and the same will be reviewed before development can begin.

## Rider Profile
This is expected to contain key rider profile info such as Name, Contact no., E-mail ID, Photo (stored in S3) with a unique ID as primary key and can be UUID. This unique ID is not the Rider ID but say profile ID. This is a master profile data which can include both riders of the current tour and previous tour participants. There can also be other riders how are yet to participate in a tour but are part of the community.

Following data are required to begin with.
- Name
- Contact no
- Email ID
- Photo 
- Emergency Contact name & No.

Other info about the riders may also be included depending on requirements. This can be taken up during the course of the development.

This data is will not change based on yearly tour. Except any info related to a specific tour year is included here. For example, we the a riders part tour participation is included in the profile, then the same will get updated after every tour participation. Other profile data like contact no. or email ID may get changed only if rider changes is them and it can be any time. It is expected rider doesn't change such personal info during a tour is active.

Rider profile or data should be kept separately from tour data since tour data is specific to a tour and rider profile is constant unless rider changes it. For app performance efficiency multiple tables can be used to maintain Rider Profile data. This is a suggestion since most likely attributes listed above are required during the tour for Check-In app. However this for the design phase.

Scope of this model is to have reference of the photo in S3. Uploading is out of scope. S3 references are expected to be uploaded by tour organizers.

## Tour Riders
This is expected to have Rider ID allocated to the rider who are registered for the current tour. Rider ID is allocated couple of weeks before the tour commences and will be uploaded by tour organizers to the corresponding table as per the format/model. Rider ID is specific to a tour and will be different for same rider for each tour rider participates. This essentially a mapping between a Tour and Rider profile data.

Tour rider participation status must support an operational exit flow. A rider can leave the tour voluntarily or be forced out by organizers for violations. This action must update the existing TourRider row only by setting `status` to `EXITED`, storing the previous status in `prevStatus`, and capturing audit attributes `exitedAt` and `exitedBy`. A cancellation action must restore `status` from `prevStatus` and remove `prevStatus`, `exitedAt`, and `exitedBy`.

Rider ID should start with character 'R' followed by 2 to 3 digit number. No zero filling required. For example: R1, R2, R10, R57, R87, R102.

QR Code will be generated for each participating riders with Rider ID. There can be more data in the QR code but for now let's go with only Rider ID as this alone can be used to retrieve all other info required about the rider.  Generation of QR code will be out the scope. But Check-in App will have the ability to scan these QR Code and get Rider ID for further processing.

## Ride Detail
This is expected to have info about each day's ride such as date, no. of rides for the day, no. of stages for each ride, ride status. Each ride is unique even if they are on the same day. Multiple rides on the same day usually are one after another and does not run in parallel or over laps. Following data are bare minimum expected to be maintained.  
- Ride No.
- Name (should be kept short. Ex Day1, Day2, etc.)
- Starting & Finishing Place
- Description (optional)
- Date of the ride
- No. of Stages
- Distance
- Ride opening time
- Flag off time
- Ride closing time
- Ride Status (Active/Closed)

Ride No. can be sequence for the day and when combined with date will be unique. Date is the key attribute to identify today's ride. This is much easier for user to understand. However for technical reason if unique identifier is considered efficient, the it can be added and auto-generated.

There will be always 'Start' and 'Finish'  first and last stages respectively. In between, depending on no. of stages there will be 'n' no. of pit stop1, PS1, PS2, PS3, etc. Simple labels Start, 'Finish and PS'n' where 'n' is stage no. can be used. Stage numbering must be zero-based (Start = 0, then 1, 2, ...). But provision to have a different label for stages should be available. Stage definitions must also support `estimatedOpenTime` (minutes from `flagOffTime`, or from `startedAt` when the ride is started), `pitStopDuration` (minutes), and `pitStopStatus` (`OPEN` / `CLOSED`, empty when the ride is created). `estimatedTimeFromStart` is redundant and must not be used. Any further aspects of the stages are expected to be part of data model design phase and the same will be reviewed before development can begin.

Pit stop role mapping for regular check-ins must follow the ride stage definition. A user with role `PS_<n>_USER` may perform a regular check-in only when the request is for stage `n` and that stage type is `PIT_STOP`. If a ride has fewer pit stops, or the matching stage number is the `FINISH` stage, that role must not be able to perform a regular check-in for that stage.

Pit stop open and close actions must follow the same stage mapping. A user with role `PS_<n>_USER` may open or close only pit stop stage `n`, while `SUPER_USER` and `ADMINISTRATOR` may open or close any pit stop stage. These actions are valid only for `PIT_STOP` stages and only when the ride status is `STARTED`. Opening a pit stop must record the stage `openedAt` timestamp and closing it must record the stage `closedAt` timestamp.

## Check-In registry
This is expected to have each check in captured through QR Code scanning for all stages. This will also include 'Not Riding' and 'Quit Riding' check in. An exceptional manual entry for 'Quit Riding' is also possible. The following info should be captured for every check-in.
- Rider ID
- Ride no.
- Stage no.
- Check-in timestamp
- Check-in User ID.
- Not Riding indicator
- Quit Riding indicator
- Manual Entry indicator
- Location (optional)

Check-in status should be derived as follows:
- Normal check-in: Check-in timestamp, Not Riding indicator is null & Quit Riding indicator is null
- Not Riding: Not Riding indicator is 'Yes'
- Quit Riding: Quit Riding indicator is 'Yes'.

For 'Not Riding', there can be only 1 entry per Rider per ride. For 'Quit Riding' there can be multiple entries per ride which should be latest entry and all previous entries are Normal check-in at various stages before rider decided to quit.

`Quit Riding` check-ins must be permitted for users holding any `PS_<n>_USER` role, independent of the stage they are assigned to for regular pit-stop check-ins.

Manual Entry indicator should be set to 'Yes' when check-in is done manually instead of scanning QR code. Location need not be implemented for now. 

## User Profile
This is Check-in app user profile. User registration will be done by administrator and user get's notified with the access credentials. Authentication will be achieved using Amazon Cognito. But if Cognito data can't be used for Check-in App, then data required should be maintained in database. It is not known what data is required and can be finalized as part of design phase.

For now User profile is tour specific since the team's constituents can change. So user setup is expected to be done (in Cognito) and (if required) uploaded to this database before the tour commences. 

The deployment must pre-create the Cognito groups `PS_1_USER`, `PS_2_USER`, `PS_3_USER`, `PS_4_USER`, and `PS_5_USER` as the initial pit stop role set. If additional pit stop roles are ever required, deployment artifacts and Cognito group provisioning must be extended accordingly, but backend authorization must continue to work for any valid `PS_<n>_USER` group name without code changes.

# API
Since data is managed centrally in this database, access data for all apps and report generation will be provided using APIs - API Gateway HTTP API. Data model design should take this into consideration as API usage cost can be managed and kept to as low as possible.

To be taken up after data model is finalized. 

# Volume

Expected volume:
- 100 registered riders max.
- 7 to 8 rides.
- Very rarely more than 1 riders per day - Likely 1 multi-ride day once in 4 tours.
- Maintain 5 past tour data
- Concurrent App users 10 to 15.