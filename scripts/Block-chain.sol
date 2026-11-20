// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// Assignment: Student Marks Register
// Fill in every TODO. Do not change the function names.
contract MarksRegister {
    struct Student {
        string name;
        uint256 marks;
    }

    address public teacher;
    Student[] public students;

    event StudentAdded(uint256 id, string name, uint256 marks);

    constructor() {
        teacher = msg.sender;
    }

    modifier onlyTeacher() {
        require(msg.sender == teacher, "Only teacher");
        _;
    }

    function addStudent(string memory name, uint256 marks) public onlyTeacher {
        require(marks <= 100, "Marks must be 0 to 100");
        
        students.push(Student(name, marks));
        emit StudentAdded(students.length - 1, name, marks);
    }

    function getStudent(uint256 id) public view returns (string memory, uint256) {
        require(id < students.length, "Invalid id");
        
        Student memory s = students[id];
        return (s.name, s.marks);
    }

    function totalStudents() public view returns (uint256) {
        return students.length;
    }

    function average() public view returns (uint256) {
        require(students.length > 0, "No students");
        
        uint256 sum = 0;
        for (uint256 i = 0; i < students.length; i++) {
            sum += students[i].marks;
        }
        return sum / students.length;
    }

    function topper() public view returns (string memory, uint256) {
        require(students.length > 0, "No students");
        
        uint256 highestIndex = 0;
        for (uint256 i = 1; i < students.length; i++) {
            if (students[i].marks > students[highestIndex].marks) {
                highestIndex = i;
            }
        }
        return (students[highestIndex].name, students[highestIndex].marks);
    }

    // Bonus (+2): returns how many students have 50 marks or more
    function passedCount() public view returns (uint256) {
        uint256 count = 0;
        for (uint256 i = 0; i < students.length; i++) {
            if (students[i].marks >= 50) {
                count++;
            }
        }
        return count;
    }
}