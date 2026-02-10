# Introduction 

A non-competitive cycling tour is conducted every year. This involves pre-registration and registration of riders for the year's tour. During the tour ride and rider management. Apps will be developed for these use cases. Apart from these there can be data analysis and reports generation. For all these purposes data are needed. Since data is being shared across apps it needs to be maintained centrally. This document provides the data requirements.

# Use Cases
## Pre-Tour
Pre-registration and registration are the key activities before the tour can commence apart from other preparation and arrangements. Pre-registration is asking riders who are interested to participate in the tour. After cut-off a review is carried out by the tour organizers to select riders for the up coming tour. Pre-registered riders who are selected to participate in the tour will be notified. These qualified riders will take next actions (payment for one) and register for the tour.

For now this process is completely manual and only some tour data prepared from this process is uploaded to tour database before the tour commences. Otherwise this process is out of scope.

## Check-In App
An application, let's refer it as Check-in App is available for use during the tour to manage daily rides and track riders in each ride. This app will be used by Cycling Tour administrators, pit stop team and optionally by hotel front desk staff to check-in riders at various stages of the daily ride - Start - Flag Off, Pit Stop(s) and Finish.

This app will have 2 primary features:  
1. Dashboard - for Ride progress & Rider tracking  
1. Rider Check-In  

Apart from these following Admin features will also be available.  
1. Add/Modify Ride
1. Close Ride

To understand how the data is used refer to the following document from Check-In App project.
 - [App Requirements](https://github.com/kvijay77-in/poc-app/blob/main/docs/Requirements.md)
 - [Dashboard Feature](https://github.com/kvijay77-in/poc-app/blob/main/docs/Dashboard-Feature.md)

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
- Flag off time
- Ride Status (Active/Closed)

Ride No. can be sequence for the day and when combined with date will be unique. Date is the key attribute to identify today's ride. This is much easier for user to understand. However for technical reason if unique identifier is considered efficient, the it can be added and auto-generated.

There will be always 'Start' and 'Finish'  first and last stages respectively. In between, depending on no. of stages there will be 'n' no. of pit stop1, PS1, PS2, PS3, etc. Simple labels Start, 'Finish and PS'n' where 'n' is stage no. can be used. But provision to have a different label for stages should be available. Any further aspects of the stages are expected to be part of data model design phase and the same will be reviewed before development can begin.

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

Manual Entry indicator should be set to 'Yes' when check-in is done manually instead of scanning QR code. Location need not be implemented for now. 

## User Profile
This is Check-in app user profile. User registration will be done by administrator and user get's notified with the access credentials. Authentication will be achieved using Amazon Cognito. But if Cognito data can't be used for Check-in App, then data required should be maintained in database. It is not known what data is required and can be finalized as part of design phase.

For now User profile is tour specific since the team's constituents can change. So user setup is expected to be done (in Cognito) and (if required) uploaded to this database before the tour commences. 

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