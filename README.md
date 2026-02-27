# data_transform
Lambda function for transforming archival data from ArchivesSpace into the
RAC's data model.

## Getting Started

With [git](https://git-scm.com/) installed, pull down the source code and move into the newly created directory:

```
git clone https://github.com/RockefellerArchiveCenter/data_transform.git
cd data_transform
```

## Service Flow

The service:
- Receives an SQS event message
- SQS triggers the Lambda
- Iterates over the records in the event message
- Transforms data based on the included mappings and schema
- Validates the transformed data against schemas
- Publishes results to SNS

## Usage

This repository is intended to be deployed as a Lambda script in AWS infrastructure.

### Expected Message Format

The script is designed to consume message from an AWS Simple Queue Service (SQS) queue. These messages are expected have the following attributes:
- `Records` must exist (array)
- Each record must contain:
  - `messageId`
  - `body` (string — JSON)

The body of the message must deserialize into one of three valid JSON shapes:
- `object_type` is provided and `data` contains the source record
- `object_type` is provided and `record` contains the source record
- `object_type` is omitted from the body but provided as an SQS message attribute.

At minimum, the source record must:
- Be a JSON object (dict)
- Include a uri
- Match the expected structure for the mapping class associated with object_type

## License

This code is released under the MIT License.

## Contributing

This is an open source project and we welcome contributions! If you want to fix a bug, or have an idea of how to enhance the application, the process looks like this:

1. File an issue in this repository. This will provide a location to discuss proposed implementations of fixes or enhancements, and can then be tied to a subsequent pull request.
2. If you have an idea of how to fix the bug (or make the improvements), fork the repository and work in your own branch. When you are done, push the branch back to this repository and set up a pull request. Automated unit tests are run on all pull requests. Any new code should have unit test coverage, documentation (if necessary), and should conform to the Python PEP8 style guidelines.
3. After some back and forth between you and core committers (or individuals who have privileges to commit to the base branch of this repository), your code will probably be merged, perhaps with some minor changes.

This repository contains a configuration file for git [pre-commit](https://pre-commit.com/) hooks which help ensure that code is linted before it is checked into version control. It is strongly recommended that you install these hooks locally by installing pre-commit and running `pre-commit install`.

## Tests

New code should have unit tests. Tests can be run using [tox](https://tox.readthedocs.io/).
