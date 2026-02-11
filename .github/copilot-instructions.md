# Instructions for GitHub Copilot for the Project

## Primary Instructions
These instructions are general for our interaction and MUST BE STRICTLY FOLLOWED.
- /docs/Requirements.md must be read and understood before any development work is taken up.
- /docs/SolutionDesign.md must be referred to for design principles and architecture.
- Follow the project folder structure as described in /docs/project-structure.md for placing files and organizing code. Any changes to the structure must be flagged for review and once approved should be updated in that document.
- Always refer to /docs/Requirements.md for any clarifications on features, functions, and requirements.
- If any inputs during our interaction contradict the requirement, flag it and ask for clarifications.
- Understand the overall project requirements, features, and constraints as described in /docs/Requirements.md.
- Ensure all code suggestions and implementations strictly adhere to the requirements specified in /docs/Requirements.md. 
- Always follow what was asked, do not code extra features or changes unless explicitly requested.
- Follow instructions and do not deviate from the task at hand.
- Do not go overboard and keep suggestions concise and relevant.
- Stick to design and instructions.
- Always ask for clarifications if the requirements are ambiguous or incomplete.
- Always prioritize security, performance, and maintainability in code suggestions.
- Always provide brief explanation on any command that you are running or suggesting to run.
- Scope of woks is strictly limited to this project and its requirements. Other project docs and code give ONLY for reference and understanding of the context.

## Technology Stack and design considerations
- Platform: None - This is purely a backend project.
- Programming Languages: Python.
- AWS Services: DynamoDB, Lambda, API Gateway, S3.
- Infrastructure as Code: AWS CloudFormation and AWS SAM.
- Authentication and Authorization: AWS Cognito.
- CI/CD: GitHub Actions. 


### Design Considerations
- HTTP APIs must be created instead of Rest API
- Use DynamoDB as the primary database for storing data.
- Use AWS Lambda functions for business logic and processing.
- Use API Gateway HTTP APIs to expose Lambda functions as RESTful endpoints.
- Use AWS S3 for any file storage needs.
- Use AWS Cognito for user authentication and authorization.
- Use AWS CloudFormation and AWS SAM for infrastructure as code and deployment.
- Ensure proper IAM roles and policies are in place for secure access to AWS resources.
- Follow best practices for serverless application development on AWS.
- Implement proper error handling and logging using AWS CloudWatch.
- Ensure the application is designed for cost efficiency on AWS.
- DynamoDB tables must be designed for optimal performance and cost.
- Use AWS SAM CLI for local development and testing of Lambda functions.
- Follow security best practices for AWS services and serverless applications.
- Ensure scalability and high availability of the application.
- Ensure proper versioning and documentation of the infrastructure as code templates.
- Ensure compliance with relevant data protection and privacy regulations.


## Library and Package Usage
- Use only well-known and widely accepted libraries and packages.
- Libraries used in the project must be open source and free to use. No paid or proprietary libraries are allowed.
- Do not use any obscure or less known libraries without prior approval.
- Always prefer libraries that are actively maintained and have good community support.
- Keep the number of external dependencies to a minimum to reduce potential security vulnerabilities.


## Coding Standards and Best Practices
- Strictly follow security best practices for mobile and web applications.
- Data protection and user privacy must be prioritized.
- Optimize code for performance and efficiency.
- Use environment variables for sensitive information and configuration settings.
- No hardcoding of any credentials, URLs, or configuration values directly in the codebase.
- Ensure proper error handling and logging should be implemented.
- Follow consistent coding style and conventions throughout the codebase.
- Use proper linting for code formatting and linting.
- Always run linting to ensure code quality before compilation and deployment.
- Write unit tests for critical components and functions.
- Document code with comments where necessary.

### Additional Guidelines
- Ensure code is modular and reusable. 
- Follow RESTful principles for any additional API development.

### AWS Cost Management
- Always look for free tier options and optimize resource usage.
- Carefully manage AWS resources to avoid unnecessary costs.
- Any redundant or unused resources should be identified and removed promptly.
- DynamoDB table design should avoid excessive read/write capacity to minimize costs.

### Resource Creation and Management
- All resources created for this project must be tagged properly for easy identification and cost tracking.
- Tags should include project name, environment (dev, test, prod) and additional relevant metadata as needed to allow granular cost allocation.


# Do's and Don'ts
Some specific or explicit instructions that must be followed. Same will be updated here if not covered above.  

## Do's
- Implement testing frameworks and write unit tests for critical components.
- Ensure proper documentation of code and infrastructure as code templates.
- Regularly review and update dependencies to ensure security and compatibility.

## Don'ts
- Never add testing or debugging code in the production codebase.


