// Invoke with repository owner, name, branch and a private token parameter.
(Owner as text, Repository as text, Branch as text, GitHubToken as text) as record =>
let
    Response = Web.Contents(
        "https://api.github.com",
        [
            RelativePath = "repos/" & Owner & "/" & Repository & "/contents/data/dataset.json",
            Query = [ref = Branch],
            Headers = [
                Accept = "application/vnd.github.raw+json",
                Authorization = "Bearer " & GitHubToken,
                #"X-GitHub-Api-Version" = "2022-11-28"
            ]
        ]
    ),
    Dataset = Json.Document(Response),
    Names = {"commits", "pull_requests", "reviews", "builds", "deployments", "incidents"},
    Tables = List.Transform(Names, (Name) => Table.FromRecords(Record.Field(Dataset, Name)))
in
    Record.FromList(Tables, Names)